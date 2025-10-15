"""
Unit tests for rate limiter implementation.
[CTX:PBI-0:0-3:RL]

Tests cover:
- Token bucket mechanics with fake time
- Rate limiting and throttling
- Adaptive rate adjustment from headers
- 429 handling with Retry-After
- 5xx retry logic
- Concurrency control
"""
import asyncio
import pytest
import threading
import time
from unittest.mock import Mock

from pred_mkts.core.config import ExchangeConfig
from pred_mkts.core.datasource import RequestSpec
from pred_mkts.core.rate_limiter import (
    FakeTimeProvider,
    RateLimiter,
    RateLimiterStats,
    SystemTimeProvider,
    TokenBucket,
)


# [CTX:PBI-0:0-3:RL] Test fixtures
@pytest.fixture
def fake_time():
    """Provide fake time provider for deterministic tests."""
    return FakeTimeProvider(initial_time=1000.0)


@pytest.fixture
def exchange_config():
    """Provide standard exchange config."""
    return ExchangeConfig(
        host="api.test.com",
        steady_rate=10,  # 10 tokens/sec
        burst=20,
        max_concurrency=4,
        headers={
            "retry_after": "Retry-After",
            "limit": "X-RateLimit-Limit",
            "remaining": "X-RateLimit-Remaining",
            "reset": "X-RateLimit-Reset",
        }
    )


@pytest.fixture
def request_spec():
    """Provide standard request spec."""
    return RequestSpec(
        url="https://api.test.com/v1/markets",
        method="GET",
        headers={},
        query_params={}
    )


# [CTX:PBI-0:0-3:RL] TimeProvider tests
class TestTimeProvider:
    """Test time provider implementations."""
    
    def test_system_time_provider(self):
        """System time provider returns current time."""
        provider = SystemTimeProvider()
        t1 = provider.now()
        time.sleep(0.01)
        t2 = provider.now()
        assert t2 > t1
    
    def test_fake_time_provider_initial(self):
        """Fake time provider starts at initial time."""
        provider = FakeTimeProvider(initial_time=100.0)
        assert provider.now() == 100.0
    
    def test_fake_time_provider_advance(self):
        """Fake time provider can advance time."""
        provider = FakeTimeProvider(initial_time=100.0)
        provider.advance(50.0)
        assert provider.now() == 150.0
    
    def test_fake_time_provider_set(self):
        """Fake time provider can set absolute time."""
        provider = FakeTimeProvider(initial_time=100.0)
        provider.set(500.0)
        assert provider.now() == 500.0
    
    def test_fake_time_provider_thread_safe(self):
        """Fake time provider is thread-safe."""
        provider = FakeTimeProvider(initial_time=0.0)
        results = []
        
        def advance_time():
            for _ in range(100):
                provider.advance(1.0)
        
        def read_time():
            for _ in range(100):
                results.append(provider.now())
        
        threads = [
            threading.Thread(target=advance_time),
            threading.Thread(target=read_time),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All reads should be valid
        assert all(isinstance(r, (int, float)) for r in results)


# [CTX:PBI-0:0-3:RL] TokenBucket tests
class TestTokenBucket:
    """Test token bucket implementation."""
    
    def test_bucket_initialization(self, fake_time):
        """Bucket initializes with correct capacity."""
        bucket = TokenBucket(
            rate=10.0,
            capacity=20,
            time_provider=fake_time
        )
        assert bucket.peek() == 20
    
    def test_bucket_initialization_custom_tokens(self, fake_time):
        """Bucket can initialize with custom token count."""
        bucket = TokenBucket(
            rate=10.0,
            capacity=20,
            time_provider=fake_time,
            initial_tokens=5
        )
        assert bucket.peek() == 5
    
    def test_bucket_consume_success(self, fake_time):
        """Consuming tokens when available succeeds."""
        bucket = TokenBucket(
            rate=10.0,
            capacity=20,
            time_provider=fake_time
        )
        assert bucket.consume(5) is True
        assert bucket.peek() == 15
    
    def test_bucket_consume_failure(self, fake_time):
        """Consuming tokens when unavailable fails."""
        bucket = TokenBucket(
            rate=10.0,
            capacity=20,
            time_provider=fake_time,
            initial_tokens=3
        )
        assert bucket.consume(5) is False
        assert bucket.peek() == 3  # No tokens consumed
    
    def test_bucket_refill(self, fake_time):
        """Bucket refills tokens over time."""
        bucket = TokenBucket(
            rate=10.0,  # 10 tokens/sec
            capacity=20,
            time_provider=fake_time,
            initial_tokens=0
        )
        
        # Advance 2 seconds -> should get 20 tokens (capped at capacity)
        fake_time.advance(2.0)
        assert bucket.peek() == 20
    
    def test_bucket_refill_partial(self, fake_time):
        """Bucket refills partial tokens correctly."""
        bucket = TokenBucket(
            rate=10.0,  # 10 tokens/sec
            capacity=20,
            time_provider=fake_time,
            initial_tokens=5
        )
        
        # Advance 1 second -> should get 10 more tokens = 15 total
        fake_time.advance(1.0)
        assert bucket.peek() == 15
    
    def test_bucket_refill_capped(self, fake_time):
        """Bucket refill is capped at capacity."""
        bucket = TokenBucket(
            rate=10.0,
            capacity=20,
            time_provider=fake_time,
            initial_tokens=15
        )
        
        # Advance 10 seconds -> should cap at 20
        fake_time.advance(10.0)
        assert bucket.peek() == 20
    
    def test_bucket_time_until_tokens(self, fake_time):
        """Calculate time until tokens available."""
        bucket = TokenBucket(
            rate=10.0,  # 10 tokens/sec
            capacity=20,
            time_provider=fake_time,
            initial_tokens=5
        )
        
        # Need 10 tokens, have 5 -> need 5 more = 0.5 seconds
        assert bucket.time_until_tokens(10) == pytest.approx(0.5)
    
    def test_bucket_time_until_tokens_available(self, fake_time):
        """Time until tokens is 0 when already available."""
        bucket = TokenBucket(
            rate=10.0,
            capacity=20,
            time_provider=fake_time,
            initial_tokens=15
        )
        
        assert bucket.time_until_tokens(10) == 0.0
    
    def test_bucket_no_time_mismatch(self, fake_time):
        """
        CRITICAL: Verify no time mismatch between initialization and usage.
        
        This test ensures the bucket uses time_provider consistently,
        preventing the infinite loop crash from time mismatches.
        """
        bucket = TokenBucket(
            rate=10.0,
            capacity=20,
            time_provider=fake_time,
            initial_tokens=10
        )
        
        # Consume some tokens
        assert bucket.consume(5) is True
        assert bucket.peek() == 5
        
        # Advance time - this should refill properly
        fake_time.advance(1.0)
        
        # Should have gained 10 tokens -> 15 total
        assert bucket.peek() == 15
        
        # Critically: no negative elapsed time, no infinite loop
        assert bucket.consume(15) is True


# [CTX:PBI-0:0-3:RL] RateLimiter basic tests
class TestRateLimiterBasic:
    """Test basic rate limiter functionality."""
    
    def test_rate_limiter_initialization(self, exchange_config, fake_time):
        """Rate limiter initializes correctly."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        assert limiter.config == exchange_config
        assert limiter.time_provider == fake_time
    
    def test_acquire_no_wait(self, exchange_config, fake_time, request_spec):
        """Acquiring with available tokens doesn't wait."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        with limiter.acquire(request_spec) as guard:
            assert guard.wait_time == 0.0
            assert guard.bucket_key == "api.test.com"
    
    def test_acquire_creates_bucket(self, exchange_config, fake_time, request_spec):
        """Acquire creates bucket on first use."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        assert len(limiter._buckets) == 0
        
        with limiter.acquire(request_spec):
            pass
        
        assert len(limiter._buckets) == 1
        assert "api.test.com" in limiter._buckets
    
    def test_burst_handling(self, exchange_config, fake_time, request_spec):
        """Rate limiter handles burst correctly."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Burst capacity is 20, should handle 20 immediate requests
        for i in range(20):
            with limiter.acquire(request_spec) as guard:
                assert guard.wait_time == 0.0, f"Request {i} should not wait"
    
    def test_steady_rate(self, exchange_config, fake_time, request_spec):
        """Rate limiter enforces steady rate after burst."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Exhaust burst (20 tokens)
        for _ in range(20):
            with limiter.acquire(request_spec):
                pass
        
        # Next request should need to wait
        # Rate is 10/sec, so need to wait ~0.1 sec per token
        # We'll advance time to allow the request
        
        # Start the acquire in a thread since it will block
        result = {}
        
        def do_acquire():
            with limiter.acquire(request_spec) as guard:
                result["wait_time"] = guard.wait_time
        
        thread = threading.Thread(target=do_acquire)
        thread.start()
        
        # Give thread time to start blocking
        time.sleep(0.01)
        
        # Advance fake time to refill 1 token
        fake_time.advance(0.1)
        
        # Wait for thread
        thread.join(timeout=1.0)
        
        # Should have waited
        assert "wait_time" in result
        assert result["wait_time"] > 0
    
    def test_stats_tracking(self, exchange_config, fake_time, request_spec):
        """Rate limiter tracks statistics."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Make some requests
        for _ in range(5):
            with limiter.acquire(request_spec):
                pass
        
        stats = limiter.get_stats()
        assert stats.requests_total == 5
        assert stats.requests_throttled == 0  # Within burst capacity
    
    def test_stats_reset(self, exchange_config, fake_time, request_spec):
        """Rate limiter can reset statistics."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        with limiter.acquire(request_spec):
            pass
        
        assert limiter.get_stats().requests_total == 1
        
        limiter.reset_stats()
        assert limiter.get_stats().requests_total == 0


# [CTX:PBI-0:0-3:RL] Header-based adaptive rate tests
class TestAdaptiveRate:
    """Test adaptive rate adjustment from headers."""
    
    def test_parse_rate_limit_headers(self, exchange_config, fake_time):
        """Parse X-RateLimit-* headers correctly."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        headers = {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "50",
            "X-RateLimit-Reset": "1060.0",  # 60 seconds from fake time start
        }
        
        parsed = limiter._parse_rate_limit_headers(headers)
        assert parsed == {
            "limit": 100,
            "remaining": 50,
            "reset": 1060.0,
        }
    
    def test_parse_rate_limit_headers_missing(self, exchange_config, fake_time):
        """Handle missing rate limit headers."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        headers = {}
        parsed = limiter._parse_rate_limit_headers(headers)
        assert parsed is None
    
    def test_adaptive_rate_adjustment(self, exchange_config, fake_time, request_spec):
        """Adjust bucket rate based on server limits."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Create bucket
        bucket = limiter._get_or_create_bucket("api.test.com")
        initial_rate = bucket.rate
        assert initial_rate == 10.0
        
        # Simulate response with rate limit headers
        # Limit: 200 tokens, Reset: 1020.0 (20 seconds from now)
        # New rate should be 200/20 = 10 tokens/sec (no change in this case)
        headers = {
            "X-RateLimit-Limit": "200",
            "X-RateLimit-Remaining": "100",
            "X-RateLimit-Reset": "1020.0",
        }
        
        limiter.handle_response_headers(request_spec, headers, 200)
        
        # Rate should be unchanged (200/20 = 10)
        assert bucket.rate == pytest.approx(10.0)
    
    def test_adaptive_rate_increase(self, exchange_config, fake_time, request_spec):
        """Increase rate when server allows higher limit."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        bucket = limiter._get_or_create_bucket("api.test.com")
        assert bucket.rate == 10.0
        
        # Server allows 500 tokens over 20 seconds = 25 tokens/sec
        headers = {
            "X-RateLimit-Limit": "500",
            "X-RateLimit-Remaining": "400",
            "X-RateLimit-Reset": "1020.0",
        }
        
        limiter.handle_response_headers(request_spec, headers, 200)
        
        # Rate should increase
        assert bucket.rate == pytest.approx(25.0)
        assert limiter.get_stats().adaptive_adjustments == 1
    
    def test_sleep_until_reset_when_exhausted(self, exchange_config, fake_time, request_spec):
        """Sleep until reset when rate limit exhausted."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Headers indicate limit exhausted, resets in 30 seconds
        headers = {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1030.0",  # 30 seconds from fake time
        }
        
        wait_time = limiter.handle_response_headers(request_spec, headers, 200)
        
        # Should return wait time until reset
        assert wait_time == pytest.approx(30.0)
        assert limiter.get_stats().requests_throttled == 1


# [CTX:PBI-0:0-3:RL] 429 handling tests
class TestHandle429:
    """Test 429 response handling."""
    
    def test_parse_retry_after_seconds(self, exchange_config, fake_time):
        """Parse Retry-After header as seconds."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        wait_time = limiter._parse_retry_after("60")
        assert wait_time == 60.0
    
    def test_parse_retry_after_http_date(self, exchange_config, fake_time):
        """Parse Retry-After header as HTTP date."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Set fake time to a known value
        fake_time.set(1000.0)
        
        # HTTP date 120 seconds in the future
        # Note: This is tricky with fake time, so we'll use a specific format
        wait_time = limiter._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT")
        
        # Should parse successfully (exact value depends on epoch)
        assert wait_time is not None
        assert isinstance(wait_time, (int, float))
    
    def test_parse_retry_after_invalid(self, exchange_config, fake_time):
        """Handle invalid Retry-After header."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        wait_time = limiter._parse_retry_after("invalid")
        assert wait_time is None
    
    def test_429_with_retry_after(self, exchange_config, fake_time, request_spec):
        """Handle 429 with Retry-After header."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        headers = {"Retry-After": "30"}
        wait_time = limiter.handle_response_headers(request_spec, headers, 429)
        
        assert wait_time == 30.0
        assert limiter.get_stats().requests_429 == 1
    
    def test_429_without_retry_after(self, exchange_config, fake_time, request_spec):
        """Handle 429 without Retry-After, use backoff."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        headers = {}
        wait_time = limiter.handle_response_headers(request_spec, headers, 429)
        
        # Should use exponential backoff (base 1.0 with jitter)
        assert wait_time is not None
        assert 0.75 <= wait_time <= 1.5  # Base 1.0 ± 25% jitter
        assert limiter.get_stats().requests_429 == 1
    
    def test_should_retry_429(self, exchange_config, fake_time):
        """Always retry 429 responses."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        assert limiter.should_retry(429, 0) is True
        assert limiter.should_retry(429, 5) is True  # No limit on 429 retries


# [CTX:PBI-0:0-3:RL] 5xx handling tests
class TestHandle5xx:
    """Test 5xx response handling."""
    
    def test_5xx_response(self, exchange_config, fake_time, request_spec):
        """Handle 5xx response with backoff."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        headers = {}
        wait_time = limiter.handle_response_headers(request_spec, headers, 503)
        
        # Should use exponential backoff
        assert wait_time is not None
        assert 0.75 <= wait_time <= 1.5  # Base 1.0 ± 25% jitter
        assert limiter.get_stats().requests_5xx == 1
    
    def test_should_retry_5xx_idempotent(self, exchange_config, fake_time):
        """Retry 5xx for idempotent methods."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        assert limiter.should_retry(500, 0, "GET") is True
        assert limiter.should_retry(503, 0, "HEAD") is True
        assert limiter.should_retry(502, 0, "PUT") is True
        assert limiter.should_retry(504, 0, "DELETE") is True
    
    def test_should_not_retry_5xx_non_idempotent(self, exchange_config, fake_time):
        """Don't retry 5xx for non-idempotent methods."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        assert limiter.should_retry(500, 0, "POST") is False
        assert limiter.should_retry(503, 0, "PATCH") is False
    
    def test_should_retry_5xx_bounded(self, exchange_config, fake_time):
        """5xx retries are bounded."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Max retries is 3
        assert limiter.should_retry(500, 0, "GET") is True
        assert limiter.should_retry(500, 1, "GET") is True
        assert limiter.should_retry(500, 2, "GET") is True
        assert limiter.should_retry(500, 3, "GET") is False
        assert limiter.should_retry(500, 4, "GET") is False
    
    def test_exponential_backoff(self, exchange_config, fake_time):
        """Exponential backoff increases with attempts."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Test without jitter for predictability
        backoff0 = limiter._calculate_backoff(0, jitter=False)
        backoff1 = limiter._calculate_backoff(1, jitter=False)
        backoff2 = limiter._calculate_backoff(2, jitter=False)
        
        # Should double each time: 1, 2, 4
        assert backoff0 == 1.0
        assert backoff1 == 2.0
        assert backoff2 == 4.0
    
    def test_exponential_backoff_capped(self, exchange_config, fake_time):
        """Exponential backoff is capped at max."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Max backoff is 60.0
        backoff = limiter._calculate_backoff(100, jitter=False)
        assert backoff == 60.0
    
    def test_exponential_backoff_jitter(self, exchange_config, fake_time):
        """Jitter adds randomness to backoff."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # With jitter, should be within ±25% of base
        backoff = limiter._calculate_backoff(0, jitter=True)
        assert 0.75 <= backoff <= 1.5


# [CTX:PBI-0:0-3:RL] Concurrency tests
class TestConcurrency:
    """Test concurrency control."""
    
    def test_concurrency_limit(self, exchange_config, fake_time, request_spec):
        """Concurrency is limited by semaphore."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Max concurrency is 4
        active_count = 0
        max_active = 0
        lock = threading.Lock()
        
        def make_request():
            nonlocal active_count, max_active
            
            with limiter.acquire(request_spec):
                with lock:
                    active_count += 1
                    max_active = max(max_active, active_count)
                
                time.sleep(0.01)
                
                with lock:
                    active_count -= 1
        
        # Start 10 concurrent requests
        threads = [threading.Thread(target=make_request) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Max active should not exceed concurrency limit
        assert max_active <= exchange_config.max_concurrency
    
    @pytest.mark.asyncio
    async def test_async_acquire(self, exchange_config, fake_time, request_spec):
        """Async acquire works correctly."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        async with limiter.acquire_async(request_spec) as guard:
            assert guard.wait_time == 0.0
            assert guard.bucket_key == "api.test.com"
    
    @pytest.mark.asyncio
    async def test_async_concurrency_limit(self, exchange_config, fake_time, request_spec):
        """Async concurrency is limited by semaphore."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        active_count = 0
        max_active = 0
        lock = asyncio.Lock()
        
        async def make_request():
            nonlocal active_count, max_active
            
            async with limiter.acquire_async(request_spec):
                async with lock:
                    active_count += 1
                    max_active = max(max_active, active_count)
                
                await asyncio.sleep(0.01)
                
                async with lock:
                    active_count -= 1
        
        # Start 10 concurrent requests
        await asyncio.gather(*[make_request() for _ in range(10)])
        
        # Max active should not exceed concurrency limit
        assert max_active <= exchange_config.max_concurrency


# [CTX:PBI-0:0-3:RL] Integration tests
class TestIntegration:
    """Integration tests for complete scenarios."""
    
    def test_full_burst_then_steady(self, exchange_config, fake_time, request_spec):
        """Test burst followed by steady rate."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Burst: 20 immediate requests
        for i in range(20):
            with limiter.acquire(request_spec) as guard:
                assert guard.wait_time == 0.0
        
        stats = limiter.get_stats()
        assert stats.requests_total == 20
        assert stats.requests_throttled == 0
        
        # Bucket is now empty, need to wait for refill
        # Rate is 10/sec, so 1 token every 0.1 sec
        bucket = limiter._get_or_create_bucket("api.test.com")
        assert bucket.peek() == 0.0
        
        # Wait 1 second -> should get 10 tokens
        fake_time.advance(1.0)
        assert bucket.peek() == 10.0
    
    def test_adaptive_then_429_then_recovery(
        self,
        exchange_config,
        fake_time,
        request_spec
    ):
        """Test adaptive rate, then 429, then recovery."""
        limiter = RateLimiter(
            exchange_config=exchange_config,
            time_provider=fake_time
        )
        
        # Start with normal requests
        with limiter.acquire(request_spec):
            pass
        
        # Server tells us we have higher limit
        headers_high = {
            "X-RateLimit-Limit": "500",
            "X-RateLimit-Remaining": "450",
            "X-RateLimit-Reset": "1020.0",
        }
        limiter.handle_response_headers(request_spec, headers_high, 200)
        
        bucket = limiter._get_or_create_bucket("api.test.com")
        assert bucket.rate == pytest.approx(25.0)
        
        # Then we hit 429
        headers_429 = {"Retry-After": "10"}
        wait_time = limiter.handle_response_headers(request_spec, headers_429, 429)
        assert wait_time == 10.0
        
        stats = limiter.get_stats()
        assert stats.requests_429 == 1
        assert stats.adaptive_adjustments == 1
        
        # After waiting, we can retry
        assert limiter.should_retry(429, 0) is True

