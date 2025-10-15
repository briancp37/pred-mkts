"""
Header-aware rate limiter with adaptive throttling.

This module implements a token bucket rate limiter that adapts to server-provided
rate limit headers and handles retries with exponential backoff.
"""
# [CTX:PBI-0:0-3:RL]

import asyncio
import random
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from pred_mkts.core.config import ExchangeConfig
from pred_mkts.core.datasource import RequestSpec


# Time provider abstraction for testability
class TimeProvider(ABC):
    """Abstract time provider for testing."""
    
    @abstractmethod
    def now(self) -> float:
        """Return current time in seconds since epoch."""
        pass
    
    @abstractmethod
    async def sleep(self, seconds: float) -> None:
        """Sleep for specified number of seconds."""
        pass


class SystemTimeProvider(TimeProvider):
    """Real time provider using system clock."""
    
    def now(self) -> float:
        """Return current time in seconds since epoch."""
        return time.time()
    
    async def sleep(self, seconds: float) -> None:
        """Sleep for specified number of seconds."""
        await asyncio.sleep(seconds)


@dataclass
class RateLimitStats:
    """Statistics for a rate limit bucket."""
    
    requests_made: int = 0
    requests_throttled: int = 0
    retries_429: int = 0
    retries_5xx: int = 0
    total_wait_time: float = 0.0
    last_request_time: float | None = None
    
    # Moving window for tracking request rate
    request_times: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    
    def record_request(self, wait_time: float = 0.0, current_time: float | None = None) -> None:
        """Record a request and its wait time."""
        if current_time is None:
            current_time = time.time()
        self.requests_made += 1
        self.total_wait_time += wait_time
        self.last_request_time = current_time
        self.request_times.append(current_time)
    
    def record_throttle(self) -> None:
        """Record a throttled request."""
        self.requests_throttled += 1
    
    def record_429_retry(self) -> None:
        """Record a 429 retry."""
        self.retries_429 += 1
    
    def record_5xx_retry(self) -> None:
        """Record a 5xx retry."""
        self.retries_5xx += 1
    
    def get_recent_rate(self, window_seconds: float = 60.0, current_time: float | None = None) -> float:
        """Get requests per second over recent window."""
        if not self.request_times:
            return 0.0
        
        if current_time is None:
            current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # Count requests in window
        recent_count = sum(1 for t in self.request_times if t >= cutoff_time)
        
        if recent_count == 0:
            return 0.0
        
        # Calculate actual window size
        oldest_in_window = min(t for t in self.request_times if t >= cutoff_time)
        actual_window = current_time - oldest_in_window
        
        if actual_window == 0:
            return 0.0
        
        return recent_count / actual_window


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""
    
    capacity: int  # Max tokens (burst size)
    refill_rate: float  # Tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    initial_time: float | None = None  # Optional initial time for testing
    
    # Adaptive rate tracking
    server_limit: int | None = None
    server_remaining: int | None = None
    server_reset: float | None = None
    
    def __post_init__(self) -> None:
        """Initialize bucket with full capacity."""
        self.tokens = float(self.capacity)
        self.last_refill = self.initial_time if self.initial_time is not None else time.time()
    
    def refill(self, current_time: float) -> None:
        """Refill tokens based on elapsed time."""
        elapsed = current_time - self.last_refill
        
        # Use adaptive rate if available
        effective_rate = self.refill_rate
        
        # If server tells us we're limited, adapt
        if self.server_reset and self.server_remaining is not None:
            time_until_reset = self.server_reset - current_time
            if time_until_reset > 0 and self.server_remaining > 0:
                # Calculate rate to stay under limit
                adaptive_rate = self.server_remaining / time_until_reset
                effective_rate = min(effective_rate, adaptive_rate)
        
        new_tokens = elapsed * effective_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = current_time
    
    def consume(self, count: int = 1) -> bool:
        """
        Try to consume tokens.
        
        Returns:
            True if tokens were available and consumed, False otherwise
        """
        if self.tokens >= count:
            self.tokens -= count
            return True
        return False
    
    def time_until_available(self, count: int = 1) -> float:
        """Calculate time until specified tokens are available."""
        if self.tokens >= count:
            return 0.0
        
        tokens_needed = count - self.tokens
        return tokens_needed / self.refill_rate
    
    def update_from_headers(
        self,
        limit: int | None = None,
        remaining: int | None = None,
        reset: float | None = None,
    ) -> None:
        """Update bucket state from server headers."""
        if limit is not None:
            self.server_limit = limit
        
        if remaining is not None:
            self.server_remaining = remaining
            # Sync our token count with server's view
            if remaining < self.tokens:
                self.tokens = float(remaining)
        
        if reset is not None:
            self.server_reset = reset


@dataclass
class RateLimitResponse:
    """Response from rate limiter with retry information."""
    
    should_retry: bool
    wait_time: float = 0.0
    reason: str = ""


class RateLimiter:
    """
    Header-aware rate limiter with adaptive throttling.
    
    Features:
    - Token bucket algorithm with per-host buckets
    - Adaptive rate based on server headers (X-RateLimit-*)
    - 429/Retry-After handling with exponential backoff
    - 5xx error handling with bounded retries
    - Concurrency control via semaphore
    """
    
    # Constants for retry logic
    MAX_RETRIES_429 = 5
    MAX_RETRIES_5XX = 3
    BASE_BACKOFF_SECONDS = 1.0
    MAX_BACKOFF_SECONDS = 60.0
    JITTER_FACTOR = 0.1
    
    def __init__(
        self,
        config: ExchangeConfig,
        time_provider: TimeProvider | None = None,
    ):
        """
        Initialize rate limiter.
        
        Args:
            config: Exchange configuration
            time_provider: Optional time provider for testing
        """
        self.config = config
        self.time_provider = time_provider or SystemTimeProvider()
        
        # Per-host token buckets
        self.buckets: dict[str, TokenBucket] = {}
        
        # Concurrency control
        self.semaphore = asyncio.Semaphore(config.max_concurrency)
        
        # Statistics tracking
        self.stats: dict[str, RateLimitStats] = defaultdict(RateLimitStats)
        
        # Retry tracking per request
        self.retry_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"429": 0, "5xx": 0}
        )
    
    def _get_bucket_key(self, request: RequestSpec) -> str:
        """Get bucket key for request."""
        # For now, use host as bucket key
        # Could be extended to support shared buckets per config
        from urllib.parse import urlparse
        return urlparse(request.url).netloc
    
    def _get_or_create_bucket(self, key: str) -> TokenBucket:
        """Get or create token bucket for key."""
        if key not in self.buckets:
            self.buckets[key] = TokenBucket(
                capacity=self.config.burst,
                refill_rate=self.config.steady_rate,
                initial_time=self.time_provider.now(),
            )
        return self.buckets[key]
    
    def _calculate_backoff(
        self,
        retry_count: int,
        max_retries: int,
    ) -> float:
        """Calculate exponential backoff with jitter."""
        if retry_count >= max_retries:
            return -1.0  # Signal no more retries
        
        # Exponential backoff: base * 2^retry_count
        backoff = self.BASE_BACKOFF_SECONDS * (2 ** retry_count)
        backoff = min(backoff, self.MAX_BACKOFF_SECONDS)
        
        # Add jitter: ±10%
        jitter = backoff * self.JITTER_FACTOR * (2 * random.random() - 1)
        return max(0.0, backoff + jitter)
    
    def _parse_retry_after(self, retry_after: str) -> float:
        """
        Parse Retry-After header value.
        
        Args:
            retry_after: Header value (seconds or HTTP-date)
            
        Returns:
            Seconds to wait
        """
        # Try parsing as integer (delay-seconds)
        try:
            return float(retry_after)
        except ValueError:
            pass
        
        # Try parsing as HTTP-date
        try:
            reset_time = parsedate_to_datetime(retry_after)
            wait_time = (reset_time - datetime.now(reset_time.tzinfo)).total_seconds()
            return max(0.0, wait_time)
        except (ValueError, TypeError):
            pass
        
        # Default fallback
        return self.BASE_BACKOFF_SECONDS
    
    def _parse_rate_limit_headers(
        self,
        headers: dict[str, str],
    ) -> tuple[int | None, int | None, float | None]:
        """
        Parse rate limit headers.
        
        Returns:
            Tuple of (limit, remaining, reset_time)
        """
        limit = None
        remaining = None
        reset_time = None
        
        # Get header names from config
        limit_header = self.config.headers.limit
        remaining_header = self.config.headers.remaining
        reset_header = self.config.headers.reset
        
        # Parse limit
        if limit_header in headers:
            try:
                limit = int(headers[limit_header])
            except ValueError:
                pass
        
        # Parse remaining
        if remaining_header in headers:
            try:
                remaining = int(headers[remaining_header])
            except ValueError:
                pass
        
        # Parse reset (usually Unix timestamp)
        if reset_header in headers:
            try:
                reset_time = float(headers[reset_header])
            except ValueError:
                pass
        
        return limit, remaining, reset_time
    
    async def acquire(self, request: RequestSpec) -> None:
        """
        Acquire permission to make a request.
        
        This is the main entry point for rate limiting. It will:
        1. Acquire semaphore slot for concurrency control
        2. Wait for token bucket to have available tokens
        3. Consume a token
        
        Args:
            request: Request specification
        """
        bucket_key = self._get_bucket_key(request)
        bucket = self._get_or_create_bucket(bucket_key)
        stats = self.stats[bucket_key]
        
        # Acquire concurrency slot
        await self.semaphore.acquire()
        
        try:
            current_time = self.time_provider.now()
            bucket.refill(current_time)
            
            # Wait for token if needed
            wait_time = 0.0
            while not bucket.consume(1):
                stats.record_throttle()
                
                # Calculate wait time
                delay = bucket.time_until_available(1)
                
                # If server says wait until reset, honor that
                if bucket.server_reset:
                    server_wait = bucket.server_reset - current_time
                    if server_wait > 0:
                        delay = max(delay, server_wait)
                
                # Sleep and refill
                await self.time_provider.sleep(delay)
                wait_time += delay
                
                current_time = self.time_provider.now()
                bucket.refill(current_time)
            
            stats.record_request(wait_time, current_time)
            
        except Exception:
            # Release semaphore on error
            self.semaphore.release()
            raise
    
    def release(self, request: RequestSpec) -> None:
        """
        Release concurrency slot.
        
        Args:
            request: Request specification
        """
        self.semaphore.release()
    
    def handle_response(
        self,
        request: RequestSpec,
        status_code: int,
        headers: dict[str, str],
        request_id: str | None = None,
    ) -> RateLimitResponse:
        """
        Handle response and update rate limiter state.
        
        Args:
            request: Original request
            status_code: HTTP status code
            headers: Response headers
            request_id: Optional request identifier for retry tracking
            
        Returns:
            RateLimitResponse indicating if retry is needed and wait time
        """
        bucket_key = self._get_bucket_key(request)
        bucket = self._get_or_create_bucket(bucket_key)
        stats = self.stats[bucket_key]
        
        # Update bucket from headers
        limit, remaining, reset_time = self._parse_rate_limit_headers(headers)
        bucket.update_from_headers(limit, remaining, reset_time)
        
        # Handle 429 - Too Many Requests
        if status_code == 429:
            stats.record_429_retry()
            
            retry_key = request_id or id(request)
            retry_count = self.retry_counts[retry_key]["429"]
            self.retry_counts[retry_key]["429"] += 1
            
            # Parse Retry-After header
            retry_after_header = self.config.headers.retry_after
            if retry_after_header in headers:
                wait_time = self._parse_retry_after(headers[retry_after_header])
            else:
                wait_time = self._calculate_backoff(retry_count, self.MAX_RETRIES_429)
            
            if wait_time < 0 or retry_count >= self.MAX_RETRIES_429:
                return RateLimitResponse(
                    should_retry=False,
                    reason="Max 429 retries exceeded",
                )
            
            return RateLimitResponse(
                should_retry=True,
                wait_time=wait_time,
                reason=f"429 retry #{retry_count + 1}",
            )
        
        # Handle 5xx - Server Errors
        if 500 <= status_code < 600:
            stats.record_5xx_retry()
            
            retry_key = request_id or id(request)
            retry_count = self.retry_counts[retry_key]["5xx"]
            self.retry_counts[retry_key]["5xx"] += 1
            
            wait_time = self._calculate_backoff(retry_count, self.MAX_RETRIES_5XX)
            
            if wait_time < 0 or retry_count >= self.MAX_RETRIES_5XX:
                return RateLimitResponse(
                    should_retry=False,
                    reason="Max 5xx retries exceeded",
                )
            
            return RateLimitResponse(
                should_retry=True,
                wait_time=wait_time,
                reason=f"5xx retry #{retry_count + 1}",
            )
        
        # Success - clear retry counts
        if request_id:
            self.retry_counts.pop(request_id, None)
        
        return RateLimitResponse(should_retry=False)
    
    def get_stats(self, bucket_key: str | None = None) -> dict[str, RateLimitStats]:
        """
        Get statistics for buckets.
        
        Args:
            bucket_key: Optional specific bucket key, or None for all
            
        Returns:
            Dictionary of bucket statistics
        """
        if bucket_key:
            return {bucket_key: self.stats[bucket_key]}
        return dict(self.stats)


