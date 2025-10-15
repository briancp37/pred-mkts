"""
Header-aware rate limiter with token bucket algorithm.
[CTX:PBI-0:0-3:RL]

This module implements an adaptive rate limiter that:
- Uses token bucket algorithm for rate limiting
- Adapts to server-provided rate limit headers
- Handles 429 and 5xx responses with appropriate retry logic
- Supports per-host bucket management
- Provides concurrency control via semaphores
- Emits structured telemetry for monitoring
"""
import asyncio
import logging
import random
import re
import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional

from .config import ExchangeConfig
from .datasource import RequestSpec
from .telemetry import TelemetryDecision, create_event, get_recorder

logger = logging.getLogger(__name__)


# [CTX:PBI-0:0-3:RL] TimeProvider protocol for testability
class TimeProvider(ABC):
    """Protocol for providing time values, allows injection of fake time in tests."""
    
    @abstractmethod
    def now(self) -> float:
        """Return current time in seconds since epoch."""
        pass


class SystemTimeProvider(TimeProvider):
    """Real time provider using system clock."""
    
    def now(self) -> float:
        import time
        return time.time()


class FakeTimeProvider(TimeProvider):
    """Fake time provider for deterministic tests."""
    
    def __init__(self, initial_time: float = 1000.0):
        self._current_time = initial_time
        self._lock = threading.Lock()
    
    def now(self) -> float:
        with self._lock:
            return self._current_time
    
    def advance(self, seconds: float) -> None:
        """Advance time by given seconds."""
        with self._lock:
            self._current_time += seconds
    
    def set(self, time: float) -> None:
        """Set absolute time."""
        with self._lock:
            self._current_time = time


# [CTX:PBI-0:0-3:RL] Token bucket implementation
class TokenBucket:
    """
    Token bucket for rate limiting with configurable refill rate.
    
    CRITICAL: Uses injectable TimeProvider to avoid time mismatch in tests.
    """
    
    def __init__(
        self,
        rate: float,
        capacity: int,
        time_provider: TimeProvider,
        initial_tokens: Optional[int] = None
    ):
        """
        Initialize token bucket.
        
        Args:
            rate: Token refill rate (tokens per second)
            capacity: Maximum tokens in bucket (burst capacity)
            time_provider: Time provider for getting current time
            initial_tokens: Initial number of tokens (defaults to capacity)
        """
        self.rate = rate
        self.capacity = capacity
        self.time_provider = time_provider
        self._tokens = initial_tokens if initial_tokens is not None else capacity
        # CRITICAL: Use time_provider, not time.time()
        self._last_refill = self.time_provider.now()
        self._lock = threading.Lock()
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = self.time_provider.now()
        elapsed = now - self._last_refill
        
        # Add tokens based on elapsed time
        new_tokens = elapsed * self.rate
        self._tokens = min(self.capacity, self._tokens + new_tokens)
        self._last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from bucket.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            True if tokens were consumed, False if insufficient tokens
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    def peek(self) -> float:
        """Get current token count without consuming."""
        with self._lock:
            self._refill()
            return self._tokens
    
    def time_until_tokens(self, tokens: int = 1) -> float:
        """
        Calculate time until specified tokens are available.
        
        Args:
            tokens: Number of tokens needed
            
        Returns:
            Seconds until tokens available (0 if already available)
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                return 0.0
            
            tokens_needed = tokens - self._tokens
            return tokens_needed / self.rate if self.rate > 0 else float('inf')


# [CTX:PBI-0:0-3:RL] Statistics tracking
@dataclass
class RateLimiterStats:
    """Statistics for rate limiter telemetry."""
    
    requests_total: int = 0
    requests_throttled: int = 0
    requests_429: int = 0
    requests_5xx: int = 0
    total_wait_time: float = 0.0
    adaptive_adjustments: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "requests_total": self.requests_total,
            "requests_throttled": self.requests_throttled,
            "requests_429": self.requests_429,
            "requests_5xx": self.requests_5xx,
            "total_wait_time": self.total_wait_time,
            "adaptive_adjustments": self.adaptive_adjustments,
        }


# [CTX:PBI-0:0-3:RL] Rate limiter guard
@dataclass
class RateLimitGuard:
    """
    Context manager returned by RateLimiter.acquire().
    
    Attributes:
        wait_time: Time spent waiting for rate limit
        bucket_key: Key identifying which bucket was used
    """
    
    wait_time: float = 0.0
    bucket_key: str = ""


# [CTX:PBI-0:0-3:RL] Main rate limiter
class RateLimiter:
    """
    Header-aware rate limiter with adaptive rate adjustment.
    
    Features:
    - Per-host token buckets
    - Adaptive rate based on X-RateLimit-* headers
    - 429 handling with Retry-After support
    - 5xx retry with exponential backoff
    - Concurrency control via semaphores
    """
    
    def __init__(
        self,
        exchange_config: ExchangeConfig,
        time_provider: Optional[TimeProvider] = None
    ):
        """
        Initialize rate limiter.
        
        Args:
            exchange_config: Configuration for the exchange
            time_provider: Optional time provider (defaults to system time)
        """
        self.config = exchange_config
        self.time_provider = time_provider or SystemTimeProvider()
        
        # Per-host token buckets
        self._buckets: Dict[str, TokenBucket] = {}
        self._bucket_lock = threading.Lock()
        
        # Concurrency control
        self._semaphore = threading.Semaphore(exchange_config.max_concurrency)
        self._async_semaphore = asyncio.Semaphore(exchange_config.max_concurrency)
        
        # Statistics
        self._stats = RateLimiterStats()
        self._stats_lock = threading.Lock()
        
        # Retry configuration
        self._max_retries_5xx = 3
        self._base_backoff = 1.0
        self._max_backoff = 60.0
    
    def _get_bucket_key(self, request_spec: RequestSpec) -> str:
        """
        Get bucket key for request.
        
        Currently uses host-based bucketing. Could be extended to support
        per-endpoint bucketing based on config.buckets patterns.
        """
        # Simple host-based bucketing for now
        return self.config.host
    
    def _get_or_create_bucket(self, key: str) -> TokenBucket:
        """Get existing bucket or create new one."""
        with self._bucket_lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(
                    rate=self.config.steady_rate,
                    capacity=self.config.burst,
                    time_provider=self.time_provider
                )
            return self._buckets[key]
    
    def _parse_retry_after(self, retry_after: str) -> Optional[float]:
        """
        Parse Retry-After header value.
        
        Args:
            retry_after: Header value (either seconds or HTTP-date)
            
        Returns:
            Seconds to wait, or None if parse failed
        """
        # Try parsing as integer seconds
        try:
            return float(retry_after)
        except ValueError:
            pass
        
        # Try parsing as HTTP-date
        try:
            retry_date = parsedate_to_datetime(retry_after)
            now = self.time_provider.now()
            # Convert to timestamp and calculate delta
            import datetime
            retry_timestamp = retry_date.timestamp()
            wait_time = max(0, retry_timestamp - now)
            return wait_time
        except (ValueError, TypeError):
            return None
    
    def _parse_rate_limit_headers(
        self,
        headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """
        Parse X-RateLimit-* headers from response.
        
        Returns:
            Dict with 'limit', 'remaining', 'reset' if headers present
        """
        header_config = self.config.headers
        result = {}
        
        # Get header names from config
        limit_header = header_config.get("limit", "X-RateLimit-Limit")
        remaining_header = header_config.get("remaining", "X-RateLimit-Remaining")
        reset_header = header_config.get("reset", "X-RateLimit-Reset")
        
        # Parse limit
        if limit_header in headers:
            try:
                result["limit"] = int(headers[limit_header])
            except ValueError:
                pass
        
        # Parse remaining
        if remaining_header in headers:
            try:
                result["remaining"] = int(headers[remaining_header])
            except ValueError:
                pass
        
        # Parse reset (usually Unix timestamp)
        if reset_header in headers:
            try:
                result["reset"] = float(headers[reset_header])
            except ValueError:
                pass
        
        return result if result else None
    
    def _extract_relevant_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Extract relevant rate limit headers for telemetry.
        
        Args:
            headers: Full response headers
            
        Returns:
            Dict of relevant headers
        """
        relevant = {}
        header_config = self.config.headers
        
        # Standard rate limit headers
        for key in ["limit", "remaining", "reset", "retry_after"]:
            header_name = header_config.get(key)
            if header_name and header_name in headers:
                relevant[header_name] = headers[header_name]
        
        return relevant
    
    def _apply_adaptive_rate(
        self,
        bucket: TokenBucket,
        rate_info: Dict[str, Any]
    ) -> None:
        """
        Adjust bucket rate based on server-provided limits.
        
        Args:
            bucket: Token bucket to adjust
            rate_info: Parsed rate limit info from headers
        """
        if "limit" not in rate_info or "reset" not in rate_info:
            return
        
        limit = rate_info["limit"]
        reset = rate_info["reset"]
        now = self.time_provider.now()
        
        # Calculate time window
        time_until_reset = max(0, reset - now)
        
        if time_until_reset > 0:
            # Adjust rate: tokens per second = limit / window
            new_rate = limit / time_until_reset
            
            # Only adjust if significantly different
            if abs(new_rate - bucket.rate) / bucket.rate > 0.1:
                logger.info(
                    f"[CTX:PBI-0:0-3:RL] Adaptive rate adjustment: "
                    f"{bucket.rate:.2f} -> {new_rate:.2f} tokens/sec"
                )
                bucket.rate = new_rate
                
                with self._stats_lock:
                    self._stats.adaptive_adjustments += 1
    
    def _calculate_backoff(self, attempt: int, jitter: bool = True) -> float:
        """
        Calculate exponential backoff with optional jitter.
        
        Args:
            attempt: Retry attempt number (0-based)
            jitter: Whether to add random jitter
            
        Returns:
            Seconds to wait
        """
        backoff = min(self._base_backoff * (2 ** attempt), self._max_backoff)
        
        if jitter:
            # Add ±25% jitter
            jitter_factor = 0.75 + random.random() * 0.5
            backoff *= jitter_factor
        
        return backoff
    
    @contextmanager
    def acquire(self, request_spec: RequestSpec):
        """
        Acquire rate limit permission (synchronous).
        
        Args:
            request_spec: Request specification
            
        Yields:
            RateLimitGuard with wait time information
        """
        import time
        
        bucket_key = self._get_bucket_key(request_spec)
        bucket = self._get_or_create_bucket(bucket_key)
        
        # Acquire semaphore for concurrency control
        self._semaphore.acquire()
        
        try:
            # Wait for tokens
            wait_time = 0.0
            start_time = time.time()
            
            while not bucket.consume(1):
                sleep_time = bucket.time_until_tokens(1)
                if sleep_time > 0:
                    time.sleep(min(sleep_time, 0.1))  # Sleep in small increments
                    wait_time += min(sleep_time, 0.1)
            
            # Update stats
            with self._stats_lock:
                self._stats.requests_total += 1
                if wait_time > 0:
                    self._stats.requests_throttled += 1
                    self._stats.total_wait_time += wait_time
            
            guard = RateLimitGuard(wait_time=wait_time, bucket_key=bucket_key)
            
            # [CTX:PBI-0:0-5:TELEM] Emit telemetry event
            decision = TelemetryDecision.THROTTLE if wait_time > 0 else TelemetryDecision.ALLOW
            event = create_event(
                exchange=self.config.host,
                endpoint=request_spec.url,
                decision=decision,
                sleep_s=wait_time,
                bucket_key=bucket_key,
                tokens_available=bucket.peek(),
            )
            get_recorder().record(event)
            
            logger.debug(
                f"[CTX:PBI-0:0-3:RL] Acquired rate limit for {bucket_key}, "
                f"waited {wait_time:.3f}s"
            )
            
            yield guard
            
        finally:
            self._semaphore.release()
    
    @asynccontextmanager
    async def acquire_async(self, request_spec: RequestSpec):
        """
        Acquire rate limit permission (asynchronous).
        
        Args:
            request_spec: Request specification
            
        Yields:
            RateLimitGuard with wait time information
        """
        bucket_key = self._get_bucket_key(request_spec)
        bucket = self._get_or_create_bucket(bucket_key)
        
        # Acquire semaphore for concurrency control
        await self._async_semaphore.acquire()
        
        try:
            # Wait for tokens
            wait_time = 0.0
            while not bucket.consume(1):
                sleep_time = bucket.time_until_tokens(1)
                if sleep_time > 0:
                    await asyncio.sleep(min(sleep_time, 0.1))
                    wait_time += min(sleep_time, 0.1)
            
            # Update stats
            with self._stats_lock:
                self._stats.requests_total += 1
                if wait_time > 0:
                    self._stats.requests_throttled += 1
                    self._stats.total_wait_time += wait_time
            
            guard = RateLimitGuard(wait_time=wait_time, bucket_key=bucket_key)
            
            # [CTX:PBI-0:0-5:TELEM] Emit telemetry event
            decision = TelemetryDecision.THROTTLE if wait_time > 0 else TelemetryDecision.ALLOW
            event = create_event(
                exchange=self.config.host,
                endpoint=request_spec.url,
                decision=decision,
                sleep_s=wait_time,
                bucket_key=bucket_key,
                tokens_available=bucket.peek(),
            )
            get_recorder().record(event)
            
            logger.debug(
                f"[CTX:PBI-0:0-3:RL] Acquired rate limit for {bucket_key}, "
                f"waited {wait_time:.3f}s"
            )
            
            yield guard
            
        finally:
            self._async_semaphore.release()
    
    def handle_response_headers(
        self,
        request_spec: RequestSpec,
        headers: Dict[str, str],
        status_code: int,
        elapsed_ms: float = 0.0,
        attempt: int = 0
    ) -> Optional[float]:
        """
        Process response headers and return wait time if needed.
        
        Args:
            request_spec: The request that was made
            headers: Response headers
            status_code: HTTP status code
            elapsed_ms: Request duration in milliseconds
            attempt: Retry attempt number
            
        Returns:
            Seconds to wait before retry, or None if no wait needed
        """
        bucket_key = self._get_bucket_key(request_spec)
        bucket = self._get_or_create_bucket(bucket_key)
        
        # Extract relevant rate limit headers for telemetry
        relevant_headers = self._extract_relevant_headers(headers)
        
        # Parse rate limit headers for adaptive adjustment
        rate_info = self._parse_rate_limit_headers(headers)
        if rate_info:
            self._apply_adaptive_rate(bucket, rate_info)
            
            # [CTX:PBI-0:0-5:TELEM] Emit adaptive adjustment event
            event = create_event(
                exchange=self.config.host,
                endpoint=request_spec.url,
                decision=TelemetryDecision.ADAPTIVE,
                status=status_code,
                elapsed_ms=elapsed_ms,
                headers_seen=relevant_headers,
                bucket_key=bucket_key,
                attempt=attempt,
                tokens_available=bucket.peek(),
            )
            get_recorder().record(event)
            
            # Check if we're close to limit
            remaining = rate_info.get("remaining", 0)
            if remaining == 0 and "reset" in rate_info:
                reset = rate_info["reset"]
                now = self.time_provider.now()
                wait_time = max(0, reset - now)
                
                logger.warning(
                    f"[CTX:PBI-0:0-3:RL] Rate limit exhausted, "
                    f"sleeping until reset: {wait_time:.2f}s"
                )
                
                with self._stats_lock:
                    self._stats.requests_throttled += 1
                
                # [CTX:PBI-0:0-5:TELEM] Emit throttle event
                event = create_event(
                    exchange=self.config.host,
                    endpoint=request_spec.url,
                    decision=TelemetryDecision.THROTTLE,
                    status=status_code,
                    elapsed_ms=elapsed_ms,
                    sleep_s=wait_time,
                    headers_seen=relevant_headers,
                    bucket_key=bucket_key,
                    attempt=attempt,
                    tokens_available=bucket.peek(),
                )
                get_recorder().record(event)
                
                return wait_time
        
        # Handle 429
        if status_code == 429:
            with self._stats_lock:
                self._stats.requests_429 += 1
            
            # Check for Retry-After header
            retry_after_header = self.config.headers.get("retry_after", "Retry-After")
            if retry_after_header in headers:
                wait_time = self._parse_retry_after(headers[retry_after_header])
                if wait_time is not None:
                    logger.warning(
                        f"[CTX:PBI-0:0-3:RL] 429 response, "
                        f"Retry-After: {wait_time:.2f}s"
                    )
                    
                    # [CTX:PBI-0:0-5:TELEM] Emit backoff event
                    event = create_event(
                        exchange=self.config.host,
                        endpoint=request_spec.url,
                        decision=TelemetryDecision.BACKOFF_429,
                        status=status_code,
                        elapsed_ms=elapsed_ms,
                        sleep_s=wait_time,
                        headers_seen=relevant_headers,
                        bucket_key=bucket_key,
                        attempt=attempt,
                        tokens_available=bucket.peek(),
                    )
                    get_recorder().record(event)
                    
                    return wait_time
            
            # Fallback to exponential backoff
            wait_time = self._calculate_backoff(0)
            logger.warning(
                f"[CTX:PBI-0:0-3:RL] 429 response, "
                f"using backoff: {wait_time:.2f}s"
            )
            
            # [CTX:PBI-0:0-5:TELEM] Emit backoff event
            event = create_event(
                exchange=self.config.host,
                endpoint=request_spec.url,
                decision=TelemetryDecision.BACKOFF_429,
                status=status_code,
                elapsed_ms=elapsed_ms,
                sleep_s=wait_time,
                headers_seen=relevant_headers,
                bucket_key=bucket_key,
                attempt=attempt,
                tokens_available=bucket.peek(),
            )
            get_recorder().record(event)
            
            return wait_time
        
        # Handle 5xx
        if 500 <= status_code < 600:
            with self._stats_lock:
                self._stats.requests_5xx += 1
            
            # Use exponential backoff for 5xx
            wait_time = self._calculate_backoff(0)
            logger.warning(
                f"[CTX:PBI-0:0-3:RL] {status_code} response, "
                f"using backoff: {wait_time:.2f}s"
            )
            
            # [CTX:PBI-0:0-5:TELEM] Emit backoff event
            event = create_event(
                exchange=self.config.host,
                endpoint=request_spec.url,
                decision=TelemetryDecision.BACKOFF_5XX,
                status=status_code,
                elapsed_ms=elapsed_ms,
                sleep_s=wait_time,
                headers_seen=relevant_headers,
                bucket_key=bucket_key,
                attempt=attempt,
                tokens_available=bucket.peek(),
            )
            get_recorder().record(event)
            
            return wait_time
        
        return None
    
    def should_retry(
        self,
        status_code: int,
        attempt: int,
        method: str = "GET"
    ) -> bool:
        """
        Determine if request should be retried.
        
        Args:
            status_code: HTTP status code
            attempt: Current attempt number (0-based)
            method: HTTP method
            
        Returns:
            True if should retry
        """
        # Always retry 429
        if status_code == 429:
            return True
        
        # Retry 5xx with bounded attempts
        if 500 <= status_code < 600:
            # Only retry idempotent methods
            if method.upper() not in ("GET", "HEAD", "PUT", "DELETE", "OPTIONS"):
                logger.warning(
                    f"[CTX:PBI-0:0-3:RL] Not retrying {status_code} for "
                    f"non-idempotent method {method}"
                )
                return False
            
            # Check retry limit
            if attempt >= self._max_retries_5xx:
                logger.error(
                    f"[CTX:PBI-0:0-3:RL] Max retries ({self._max_retries_5xx}) "
                    f"exceeded for {status_code}"
                )
                return False
            
            return True
        
        return False
    
    def get_stats(self) -> RateLimiterStats:
        """Get current statistics."""
        with self._stats_lock:
            return RateLimiterStats(
                requests_total=self._stats.requests_total,
                requests_throttled=self._stats.requests_throttled,
                requests_429=self._stats.requests_429,
                requests_5xx=self._stats.requests_5xx,
                total_wait_time=self._stats.total_wait_time,
                adaptive_adjustments=self._stats.adaptive_adjustments,
            )
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        with self._stats_lock:
            self._stats = RateLimiterStats()

