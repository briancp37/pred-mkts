"""
Structured telemetry for rate limiter and DataSource operations.
[CTX:PBI-0:0-5:TELEM]

This module provides structured logging capabilities for understanding:
- API utilization patterns
- Throttling events and reasons
- Retry behavior and backoff decisions
- Response header patterns from exchanges
"""
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TelemetryLevel(Enum):
    """Telemetry verbosity levels."""
    INFO = "info"
    DEBUG = "debug"


class TelemetryDecision(Enum):
    """Rate limiter decision types."""
    ALLOW = "allow"              # Request allowed immediately
    THROTTLE = "throttle"        # Request throttled, tokens unavailable
    BACKOFF_429 = "backoff_429"  # Backing off due to 429 response
    BACKOFF_5XX = "backoff_5xx"  # Backing off due to 5xx response
    ADAPTIVE = "adaptive"        # Rate adjusted based on headers


# [CTX:PBI-0:0-5:TELEM] Telemetry event structure
@dataclass
class TelemetryEvent:
    """
    A single telemetry event capturing rate limiter or DataSource activity.
    
    Attributes:
        timestamp: ISO 8601 timestamp of event
        exchange: Exchange/host name (e.g., "polymarket")
        endpoint: API endpoint being accessed
        status: HTTP status code (None if not yet executed)
        elapsed_ms: Request duration in milliseconds
        decision: Rate limiter decision (allow, throttle, backoff, etc.)
        sleep_s: Time slept due to rate limiting
        headers_seen: Relevant rate limit headers from response
        bucket_key: Rate limit bucket identifier
        attempt: Retry attempt number (0 for first attempt)
        tokens_available: Number of tokens available in bucket
    """
    timestamp: str
    exchange: str
    endpoint: str
    status: Optional[int]
    elapsed_ms: float
    decision: str
    sleep_s: float = 0.0
    headers_seen: Dict[str, str] = field(default_factory=dict)
    bucket_key: str = ""
    attempt: int = 0
    tokens_available: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for logging."""
        return {k: v for k, v in asdict(self).items() if v is not None or k == "status"}
    
    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), default=str)
    
    def to_keyvalue(self) -> str:
        """Convert event to key=value format."""
        pairs = []
        for key, value in self.to_dict().items():
            if isinstance(value, dict):
                # Flatten nested dicts
                for subkey, subval in value.items():
                    pairs.append(f"{key}.{subkey}={subval}")
            else:
                pairs.append(f"{key}={value}")
        return " ".join(pairs)


# [CTX:PBI-0:0-5:TELEM] In-memory statistics tracker
@dataclass
class TelemetryStats:
    """
    Aggregated statistics for telemetry analysis.
    
    Useful for tests and runtime monitoring.
    """
    total_requests: int = 0
    total_sleeps: int = 0
    total_sleep_time: float = 0.0
    total_elapsed_time: float = 0.0
    decisions_by_type: Dict[str, int] = field(default_factory=dict)
    status_codes: Dict[int, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        avg_latency = (
            self.total_elapsed_time / self.total_requests
            if self.total_requests > 0
            else 0.0
        )
        
        return {
            "total_requests": self.total_requests,
            "total_sleeps": self.total_sleeps,
            "total_sleep_time": self.total_sleep_time,
            "avg_latency_ms": round(avg_latency, 2),
            "decisions_by_type": self.decisions_by_type,
            "status_codes": self.status_codes,
        }


# [CTX:PBI-0:0-5:TELEM] Main telemetry recorder
class TelemetryRecorder:
    """
    Records and emits structured telemetry for rate limiter operations.
    
    Features:
    - Structured logging in JSON or key=value format
    - Configurable verbosity (info/debug)
    - Optional in-memory statistics collection
    - Thread-safe operation
    """
    
    def __init__(
        self,
        level: TelemetryLevel = TelemetryLevel.INFO,
        format_json: bool = True,
        collect_stats: bool = False
    ):
        """
        Initialize telemetry recorder.
        
        Args:
            level: Logging verbosity level
            format_json: If True, log as JSON; otherwise use key=value
            collect_stats: If True, collect in-memory statistics
        """
        self.level = level
        self.format_json = format_json
        self.collect_stats = collect_stats
        
        # Statistics tracking
        self._stats = TelemetryStats()
        self._stats_lock = threading.Lock()
        
        # Event history (for testing)
        self._events: List[TelemetryEvent] = []
        self._events_lock = threading.Lock()
    
    def record(self, event: TelemetryEvent) -> None:
        """
        Record a telemetry event.
        
        Args:
            event: Event to record
        """
        # Format and log event
        if self.format_json:
            log_message = f"[CTX:PBI-0:0-5:TELEM] {event.to_json()}"
        else:
            log_message = f"[CTX:PBI-0:0-5:TELEM] {event.to_keyvalue()}"
        
        # Log at appropriate level
        if self.level == TelemetryLevel.DEBUG:
            logger.debug(log_message)
        else:
            # Only log throttling and errors at INFO level
            if event.decision in [
                TelemetryDecision.THROTTLE.value,
                TelemetryDecision.BACKOFF_429.value,
                TelemetryDecision.BACKOFF_5XX.value,
                TelemetryDecision.ADAPTIVE.value,
            ] or (event.status and event.status >= 400):
                logger.info(log_message)
            else:
                logger.debug(log_message)
        
        # Update statistics
        if self.collect_stats:
            with self._stats_lock:
                self._stats.total_requests += 1
                self._stats.total_elapsed_time += event.elapsed_ms
                
                if event.sleep_s > 0:
                    self._stats.total_sleeps += 1
                    self._stats.total_sleep_time += event.sleep_s
                
                # Track decision types
                decision_key = event.decision
                self._stats.decisions_by_type[decision_key] = (
                    self._stats.decisions_by_type.get(decision_key, 0) + 1
                )
                
                # Track status codes
                if event.status:
                    self._stats.status_codes[event.status] = (
                        self._stats.status_codes.get(event.status, 0) + 1
                    )
        
        # Store event for retrieval
        with self._events_lock:
            self._events.append(event)
    
    def get_stats(self) -> TelemetryStats:
        """Get current statistics snapshot."""
        with self._stats_lock:
            return TelemetryStats(
                total_requests=self._stats.total_requests,
                total_sleeps=self._stats.total_sleeps,
                total_sleep_time=self._stats.total_sleep_time,
                total_elapsed_time=self._stats.total_elapsed_time,
                decisions_by_type=self._stats.decisions_by_type.copy(),
                status_codes=self._stats.status_codes.copy(),
            )
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        with self._stats_lock:
            self._stats = TelemetryStats()
    
    def get_events(self) -> List[TelemetryEvent]:
        """Get all recorded events (for testing)."""
        with self._events_lock:
            return self._events.copy()
    
    def clear_events(self) -> None:
        """Clear event history."""
        with self._events_lock:
            self._events.clear()


# [CTX:PBI-0:0-5:TELEM] Global telemetry recorder instance
_global_recorder: Optional[TelemetryRecorder] = None
_recorder_lock = threading.Lock()


def get_recorder() -> TelemetryRecorder:
    """
    Get the global telemetry recorder instance.
    
    Creates a default recorder if none exists.
    """
    global _global_recorder
    
    if _global_recorder is None:
        with _recorder_lock:
            if _global_recorder is None:
                _global_recorder = TelemetryRecorder()
    
    return _global_recorder


def set_recorder(recorder: TelemetryRecorder) -> None:
    """
    Set the global telemetry recorder instance.
    
    Args:
        recorder: Recorder instance to use globally
    """
    global _global_recorder
    
    with _recorder_lock:
        _global_recorder = recorder


def create_event(
    exchange: str,
    endpoint: str,
    decision: TelemetryDecision,
    status: Optional[int] = None,
    elapsed_ms: float = 0.0,
    sleep_s: float = 0.0,
    headers_seen: Optional[Dict[str, str]] = None,
    bucket_key: str = "",
    attempt: int = 0,
    tokens_available: float = 0.0,
) -> TelemetryEvent:
    """
    Helper to create a telemetry event with current timestamp.
    
    Args:
        exchange: Exchange/host name
        endpoint: API endpoint
        decision: Rate limiter decision
        status: HTTP status code
        elapsed_ms: Request duration in milliseconds
        sleep_s: Time slept due to rate limiting
        headers_seen: Relevant rate limit headers
        bucket_key: Rate limit bucket identifier
        attempt: Retry attempt number
        tokens_available: Tokens available in bucket
        
    Returns:
        TelemetryEvent ready for recording
    """
    from datetime import datetime, timezone
    
    return TelemetryEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        exchange=exchange,
        endpoint=endpoint,
        status=status,
        elapsed_ms=elapsed_ms,
        decision=decision.value,
        sleep_s=sleep_s,
        headers_seen=headers_seen or {},
        bucket_key=bucket_key,
        attempt=attempt,
        tokens_available=tokens_available,
    )

