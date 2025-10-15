"""
Unit tests for telemetry module.
[CTX:PBI-0:0-5:TELEM]

Tests verify:
- Structured event creation with required fields
- JSON and key=value formatting
- Statistics collection and aggregation
- Thread-safe recorder operations
- Event history for testing
"""
import json
import pytest
import threading
import time

from pred_mkts.core.telemetry import (
    TelemetryDecision,
    TelemetryEvent,
    TelemetryLevel,
    TelemetryRecorder,
    TelemetryStats,
    create_event,
    get_recorder,
    set_recorder,
)


# [CTX:PBI-0:0-5:TELEM] Test event creation and formatting
class TestTelemetryEvent:
    """Test TelemetryEvent data structure and serialization."""
    
    def test_event_to_dict(self):
        """Test event serialization to dictionary."""
        event = TelemetryEvent(
            timestamp="2025-10-15T09:05:00.123Z",
            exchange="api.polymarket.com",
            endpoint="/markets",
            status=200,
            elapsed_ms=234.5,
            decision="allow",
            sleep_s=0.0,
            headers_seen={"X-RateLimit-Remaining": "95"},
            bucket_key="polymarket",
            attempt=0,
            tokens_available=15.3,
        )
        
        result = event.to_dict()
        
        assert result["timestamp"] == "2025-10-15T09:05:00.123Z"
        assert result["exchange"] == "api.polymarket.com"
        assert result["endpoint"] == "/markets"
        assert result["status"] == 200
        assert result["elapsed_ms"] == 234.5
        assert result["decision"] == "allow"
        assert result["sleep_s"] == 0.0
        assert result["headers_seen"] == {"X-RateLimit-Remaining": "95"}
        assert result["bucket_key"] == "polymarket"
        assert result["attempt"] == 0
        assert result["tokens_available"] == 15.3
    
    def test_event_to_json(self):
        """Test event serialization to JSON string."""
        event = TelemetryEvent(
            timestamp="2025-10-15T09:05:00.123Z",
            exchange="api.polymarket.com",
            endpoint="/markets",
            status=200,
            elapsed_ms=234.5,
            decision="allow",
        )
        
        result = event.to_json()
        parsed = json.loads(result)
        
        assert parsed["timestamp"] == "2025-10-15T09:05:00.123Z"
        assert parsed["exchange"] == "api.polymarket.com"
        assert parsed["decision"] == "allow"
    
    def test_event_to_keyvalue(self):
        """Test event serialization to key=value format."""
        event = TelemetryEvent(
            timestamp="2025-10-15T09:05:00.123Z",
            exchange="api.polymarket.com",
            endpoint="/markets",
            status=200,
            elapsed_ms=234.5,
            decision="allow",
            headers_seen={"X-RateLimit-Remaining": "95"},
        )
        
        result = event.to_keyvalue()
        
        assert "timestamp=2025-10-15T09:05:00.123Z" in result
        assert "exchange=api.polymarket.com" in result
        assert "decision=allow" in result
        assert "status=200" in result
        assert "elapsed_ms=234.5" in result
        # Nested dict should be flattened
        assert "headers_seen.X-RateLimit-Remaining=95" in result
    
    def test_event_with_none_status(self):
        """Test event with null status (pre-request event)."""
        event = TelemetryEvent(
            timestamp="2025-10-15T09:05:00.123Z",
            exchange="api.polymarket.com",
            endpoint="/markets",
            status=None,
            elapsed_ms=0.0,
            decision="throttle",
            sleep_s=1.5,
        )
        
        result = event.to_dict()
        assert result["status"] is None  # Should include null status


# [CTX:PBI-0:0-5:TELEM] Test statistics tracking
class TestTelemetryStats:
    """Test TelemetryStats aggregation."""
    
    def test_stats_initialization(self):
        """Test stats start at zero."""
        stats = TelemetryStats()
        
        assert stats.total_requests == 0
        assert stats.total_sleeps == 0
        assert stats.total_sleep_time == 0.0
        assert stats.total_elapsed_time == 0.0
        assert stats.decisions_by_type == {}
        assert stats.status_codes == {}
    
    def test_stats_to_dict(self):
        """Test stats serialization with average calculation."""
        stats = TelemetryStats(
            total_requests=10,
            total_sleeps=3,
            total_sleep_time=5.5,
            total_elapsed_time=2345.0,
        )
        stats.decisions_by_type = {"allow": 7, "throttle": 3}
        stats.status_codes = {200: 8, 429: 2}
        
        result = stats.to_dict()
        
        assert result["total_requests"] == 10
        assert result["total_sleeps"] == 3
        assert result["total_sleep_time"] == 5.5
        assert result["avg_latency_ms"] == 234.5  # 2345.0 / 10
        assert result["decisions_by_type"] == {"allow": 7, "throttle": 3}
        assert result["status_codes"] == {200: 8, 429: 2}
    
    def test_stats_avg_latency_no_requests(self):
        """Test average latency calculation with zero requests."""
        stats = TelemetryStats()
        result = stats.to_dict()
        
        assert result["avg_latency_ms"] == 0.0


# [CTX:PBI-0:0-5:TELEM] Test recorder functionality
class TestTelemetryRecorder:
    """Test TelemetryRecorder logging and statistics."""
    
    def test_recorder_initialization(self):
        """Test recorder default initialization."""
        recorder = TelemetryRecorder()
        
        assert recorder.level == TelemetryLevel.INFO
        assert recorder.format_json is True
        assert recorder.collect_stats is False
    
    def test_recorder_custom_config(self):
        """Test recorder with custom configuration."""
        recorder = TelemetryRecorder(
            level=TelemetryLevel.DEBUG,
            format_json=False,
            collect_stats=True,
        )
        
        assert recorder.level == TelemetryLevel.DEBUG
        assert recorder.format_json is False
        assert recorder.collect_stats is True
    
    def test_recorder_collects_stats(self):
        """Test statistics collection enabled."""
        recorder = TelemetryRecorder(collect_stats=True)
        
        # Record some events
        event1 = TelemetryEvent(
            timestamp="2025-10-15T09:05:00Z",
            exchange="polymarket",
            endpoint="/markets",
            status=200,
            elapsed_ms=100.0,
            decision="allow",
            sleep_s=0.0,
        )
        
        event2 = TelemetryEvent(
            timestamp="2025-10-15T09:05:01Z",
            exchange="polymarket",
            endpoint="/markets",
            status=200,
            elapsed_ms=150.0,
            decision="throttle",
            sleep_s=1.5,
        )
        
        event3 = TelemetryEvent(
            timestamp="2025-10-15T09:05:02Z",
            exchange="polymarket",
            endpoint="/markets",
            status=429,
            elapsed_ms=200.0,
            decision="backoff_429",
            sleep_s=60.0,
        )
        
        recorder.record(event1)
        recorder.record(event2)
        recorder.record(event3)
        
        stats = recorder.get_stats()
        
        assert stats.total_requests == 3
        assert stats.total_sleeps == 2
        assert stats.total_sleep_time == 61.5
        assert stats.total_elapsed_time == 450.0
        assert stats.decisions_by_type["allow"] == 1
        assert stats.decisions_by_type["throttle"] == 1
        assert stats.decisions_by_type["backoff_429"] == 1
        assert stats.status_codes[200] == 2
        assert stats.status_codes[429] == 1
    
    def test_recorder_event_history(self):
        """Test event history tracking."""
        recorder = TelemetryRecorder()
        
        event1 = create_event(
            exchange="polymarket",
            endpoint="/markets",
            decision=TelemetryDecision.ALLOW,
        )
        
        event2 = create_event(
            exchange="kalshi",
            endpoint="/events",
            decision=TelemetryDecision.THROTTLE,
            sleep_s=1.0,
        )
        
        recorder.record(event1)
        recorder.record(event2)
        
        events = recorder.get_events()
        
        assert len(events) == 2
        assert events[0].exchange == "polymarket"
        assert events[1].exchange == "kalshi"
    
    def test_recorder_reset_stats(self):
        """Test statistics reset."""
        recorder = TelemetryRecorder(collect_stats=True)
        
        event = create_event(
            exchange="polymarket",
            endpoint="/markets",
            decision=TelemetryDecision.ALLOW,
            elapsed_ms=100.0,
        )
        recorder.record(event)
        
        stats = recorder.get_stats()
        assert stats.total_requests == 1
        
        recorder.reset_stats()
        stats = recorder.get_stats()
        assert stats.total_requests == 0
    
    def test_recorder_clear_events(self):
        """Test event history clearing."""
        recorder = TelemetryRecorder()
        
        event = create_event(
            exchange="polymarket",
            endpoint="/markets",
            decision=TelemetryDecision.ALLOW,
        )
        recorder.record(event)
        
        assert len(recorder.get_events()) == 1
        
        recorder.clear_events()
        assert len(recorder.get_events()) == 0
    
    def test_recorder_thread_safety(self):
        """Test concurrent recording from multiple threads."""
        recorder = TelemetryRecorder(collect_stats=True)
        
        def record_events(count: int):
            for i in range(count):
                event = create_event(
                    exchange="polymarket",
                    endpoint=f"/markets/{i}",
                    decision=TelemetryDecision.ALLOW,
                    elapsed_ms=100.0,
                )
                recorder.record(event)
        
        # Create 10 threads, each recording 10 events
        threads = []
        for _ in range(10):
            t = threading.Thread(target=record_events, args=(10,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        stats = recorder.get_stats()
        events = recorder.get_events()
        
        # Should have 100 total events
        assert stats.total_requests == 100
        assert len(events) == 100


# [CTX:PBI-0:0-5:TELEM] Test helper functions
class TestHelperFunctions:
    """Test module-level helper functions."""
    
    def test_create_event_with_timestamp(self):
        """Test create_event generates timestamp."""
        event = create_event(
            exchange="polymarket",
            endpoint="/markets",
            decision=TelemetryDecision.ALLOW,
        )
        
        # Should have ISO 8601 timestamp
        assert event.timestamp is not None
        assert "T" in event.timestamp
        # Accept both Z suffix and +00:00 timezone format
        assert ("Z" in event.timestamp or "+00:00" in event.timestamp)
    
    def test_create_event_all_fields(self):
        """Test create_event with all optional fields."""
        event = create_event(
            exchange="polymarket",
            endpoint="/markets",
            decision=TelemetryDecision.BACKOFF_429,
            status=429,
            elapsed_ms=234.5,
            sleep_s=60.0,
            headers_seen={"Retry-After": "60"},
            bucket_key="polymarket",
            attempt=1,
            tokens_available=10.5,
        )
        
        assert event.exchange == "polymarket"
        assert event.endpoint == "/markets"
        assert event.decision == "backoff_429"
        assert event.status == 429
        assert event.elapsed_ms == 234.5
        assert event.sleep_s == 60.0
        assert event.headers_seen == {"Retry-After": "60"}
        assert event.bucket_key == "polymarket"
        assert event.attempt == 1
        assert event.tokens_available == 10.5
    
    def test_get_recorder_singleton(self):
        """Test get_recorder returns singleton instance."""
        recorder1 = get_recorder()
        recorder2 = get_recorder()
        
        assert recorder1 is recorder2
    
    def test_set_recorder_custom(self):
        """Test set_recorder allows custom instance."""
        custom_recorder = TelemetryRecorder(
            level=TelemetryLevel.DEBUG,
            format_json=False,
        )
        
        set_recorder(custom_recorder)
        
        recorder = get_recorder()
        assert recorder is custom_recorder
        assert recorder.level == TelemetryLevel.DEBUG
        assert recorder.format_json is False
        
        # Reset to default for other tests
        set_recorder(TelemetryRecorder())


# [CTX:PBI-0:0-5:TELEM] Test decision types
class TestDecisionTypes:
    """Test TelemetryDecision enum values."""
    
    def test_decision_values(self):
        """Test all decision types have correct values."""
        assert TelemetryDecision.ALLOW.value == "allow"
        assert TelemetryDecision.THROTTLE.value == "throttle"
        assert TelemetryDecision.BACKOFF_429.value == "backoff_429"
        assert TelemetryDecision.BACKOFF_5XX.value == "backoff_5xx"
        assert TelemetryDecision.ADAPTIVE.value == "adaptive"
    
    def test_decision_usage_in_event(self):
        """Test decision enum works in event creation."""
        for decision in TelemetryDecision:
            event = create_event(
                exchange="test",
                endpoint="/test",
                decision=decision,
            )
            
            assert event.decision == decision.value


# [CTX:PBI-0:0-5:TELEM] Integration tests
class TestTelemetryIntegration:
    """Test telemetry integration with rate limiter scenarios."""
    
    def test_allow_scenario(self):
        """Test telemetry for successful request without throttling."""
        recorder = TelemetryRecorder(collect_stats=True)
        set_recorder(recorder)
        
        event = create_event(
            exchange="api.polymarket.com",
            endpoint="https://api.polymarket.com/markets",
            decision=TelemetryDecision.ALLOW,
            status=None,
            elapsed_ms=0.0,
            sleep_s=0.0,
            bucket_key="api.polymarket.com",
            tokens_available=18.7,
        )
        
        recorder.record(event)
        
        stats = recorder.get_stats()
        assert stats.total_requests == 1
        assert stats.total_sleeps == 0
        assert stats.decisions_by_type["allow"] == 1
    
    def test_throttle_scenario(self):
        """Test telemetry for throttled request."""
        recorder = TelemetryRecorder(collect_stats=True)
        set_recorder(recorder)
        
        event = create_event(
            exchange="api.polymarket.com",
            endpoint="https://api.polymarket.com/markets",
            decision=TelemetryDecision.THROTTLE,
            status=None,
            elapsed_ms=0.0,
            sleep_s=0.5,
            bucket_key="api.polymarket.com",
            tokens_available=19.2,
        )
        
        recorder.record(event)
        
        stats = recorder.get_stats()
        assert stats.total_requests == 1
        assert stats.total_sleeps == 1
        assert stats.total_sleep_time == 0.5
        assert stats.decisions_by_type["throttle"] == 1
    
    def test_429_backoff_scenario(self):
        """Test telemetry for 429 response with backoff."""
        recorder = TelemetryRecorder(collect_stats=True)
        set_recorder(recorder)
        
        event = create_event(
            exchange="api.polymarket.com",
            endpoint="https://api.polymarket.com/markets",
            decision=TelemetryDecision.BACKOFF_429,
            status=429,
            elapsed_ms=145.3,
            sleep_s=60.0,
            headers_seen={
                "Retry-After": "60",
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "0",
            },
            bucket_key="api.polymarket.com",
            attempt=0,
            tokens_available=18.7,
        )
        
        recorder.record(event)
        
        stats = recorder.get_stats()
        assert stats.total_requests == 1
        assert stats.total_sleeps == 1
        assert stats.total_sleep_time == 60.0
        assert stats.decisions_by_type["backoff_429"] == 1
        assert stats.status_codes[429] == 1
    
    def test_5xx_backoff_scenario(self):
        """Test telemetry for 5xx response with backoff."""
        recorder = TelemetryRecorder(collect_stats=True)
        set_recorder(recorder)
        
        event = create_event(
            exchange="api.polymarket.com",
            endpoint="https://api.polymarket.com/markets",
            decision=TelemetryDecision.BACKOFF_5XX,
            status=503,
            elapsed_ms=3012.1,
            sleep_s=1.0,
            bucket_key="api.polymarket.com",
            attempt=1,
            tokens_available=16.8,
        )
        
        recorder.record(event)
        
        stats = recorder.get_stats()
        assert stats.total_requests == 1
        assert stats.total_sleeps == 1
        assert stats.total_sleep_time == 1.0
        assert stats.decisions_by_type["backoff_5xx"] == 1
        assert stats.status_codes[503] == 1
    
    def test_adaptive_scenario(self):
        """Test telemetry for adaptive rate adjustment."""
        recorder = TelemetryRecorder(collect_stats=True)
        set_recorder(recorder)
        
        event = create_event(
            exchange="api.polymarket.com",
            endpoint="https://api.polymarket.com/markets",
            decision=TelemetryDecision.ADAPTIVE,
            status=200,
            elapsed_ms=234.5,
            sleep_s=0.0,
            headers_seen={
                "X-RateLimit-Limit": "150",
                "X-RateLimit-Remaining": "145",
                "X-RateLimit-Reset": "1729000070",
            },
            bucket_key="api.polymarket.com",
            attempt=0,
            tokens_available=17.9,
        )
        
        recorder.record(event)
        
        stats = recorder.get_stats()
        assert stats.total_requests == 1
        assert stats.total_sleeps == 0
        assert stats.decisions_by_type["adaptive"] == 1
        assert stats.status_codes[200] == 1
    
    def test_multi_event_scenario(self):
        """Test telemetry for sequence of mixed events."""
        recorder = TelemetryRecorder(collect_stats=True)
        set_recorder(recorder)
        
        # 5 successful requests
        for i in range(5):
            event = create_event(
                exchange="polymarket",
                endpoint="/markets",
                decision=TelemetryDecision.ALLOW,
                elapsed_ms=100.0,
            )
            recorder.record(event)
        
        # 2 throttled requests
        for i in range(2):
            event = create_event(
                exchange="polymarket",
                endpoint="/markets",
                decision=TelemetryDecision.THROTTLE,
                sleep_s=0.5,
                elapsed_ms=100.0,
            )
            recorder.record(event)
        
        # 1 429 response
        event = create_event(
            exchange="polymarket",
            endpoint="/markets",
            decision=TelemetryDecision.BACKOFF_429,
            status=429,
            sleep_s=60.0,
            elapsed_ms=150.0,
        )
        recorder.record(event)
        
        stats = recorder.get_stats()
        
        assert stats.total_requests == 8
        assert stats.total_sleeps == 3  # 2 throttles + 1 backoff
        assert stats.total_sleep_time == 61.0  # 0.5 + 0.5 + 60.0
        assert stats.total_elapsed_time == 850.0  # 5*100 + 2*100 + 150
        assert stats.decisions_by_type["allow"] == 5
        assert stats.decisions_by_type["throttle"] == 2
        assert stats.decisions_by_type["backoff_429"] == 1
        assert stats.status_codes.get(429, 0) == 1

