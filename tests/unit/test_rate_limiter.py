"""
Unit tests for rate limiter.

Tests cover token bucket algorithm, adaptive rate limiting, retry logic,
and statistics tracking with deterministic time.
"""
# [CTX:PBI-0:0-3:RL]

import asyncio
from unittest.mock import MagicMock

import pytest

from pred_mkts.core import (
    ExchangeConfig,
    RateLimiter,
    RateLimitResponse,
    RequestSpec,
    TimeProvider,
)


class FakeTimeProvider(TimeProvider):
    """Deterministic time provider for testing."""
    
    def __init__(self, initial_time: float = 1000.0):
        self.current_time = initial_time
        self.sleep_history: list[float] = []
    
    def now(self) -> float:
        """Return current fake time."""
        return self.current_time
    
    async def sleep(self, seconds: float) -> None:
        """Simulate sleep by advancing time."""
        self.sleep_history.append(seconds)
        self.current_time += seconds
    
    def advance(self, seconds: float) -> None:
        """Manually advance time."""
        self.current_time += seconds


@pytest.fixture
def fake_time():
    """Fixture providing fake time provider."""
    return FakeTimeProvider()


@pytest.fixture
def basic_config():
    """Fixture providing basic exchange config."""
    return ExchangeConfig(
        host="api.example.com",
        steady_rate=10.0,  # 10 tokens/sec
        burst=20,
        max_concurrency=4,
    )


@pytest.fixture
def rate_limiter(basic_config, fake_time):
    """Fixture providing rate limiter with fake time."""
    return RateLimiter(basic_config, time_provider=fake_time)


@pytest.fixture
def sample_request():
    """Fixture providing sample request."""
    return RequestSpec(
        url="https://api.example.com/markets",
        method="GET",
        headers={},
        query_params={},
    )


class TestTokenBucket:
    """Test token bucket algorithm."""
    
    @pytest.mark.asyncio
    async def test_initial_burst(self, rate_limiter, sample_request, fake_time):
        """Test that initial burst allows multiple rapid requests."""
        # Should allow 20 rapid requests (burst capacity)
        for i in range(20):
            await rate_limiter.acquire(sample_request)
            rate_limiter.release(sample_request)
        
        # No sleep should have occurred
        assert len(fake_time.sleep_history) == 0
    
    @pytest.mark.asyncio
    async def test_steady_rate_throttling(
        self, rate_limiter, sample_request, fake_time
    ):
        """Test throttling at steady rate after burst."""
        # Exhaust burst
        for i in range(20):
            await rate_limiter.acquire(sample_request)
            rate_limiter.release(sample_request)
        
        # Next request should wait for token refill
        await rate_limiter.acquire(sample_request)
        rate_limiter.release(sample_request)
        
        # Should have slept to wait for next token (0.1s at 10 tokens/sec)
        assert len(fake_time.sleep_history) > 0
        assert fake_time.sleep_history[0] == pytest.approx(0.1, abs=0.01)
    
    @pytest.mark.asyncio
    async def test_token_refill_over_time(
        self, rate_limiter, sample_request, fake_time
    ):
        """Test that tokens refill over time."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        bucket = rate_limiter._get_or_create_bucket(bucket_key)
        
        # Consume all tokens
        for i in range(20):
            await rate_limiter.acquire(sample_request)
            rate_limiter.release(sample_request)
        
        assert bucket.tokens < 1.0
        
        # Advance time by 2 seconds (should refill 20 tokens at 10/sec)
        fake_time.advance(2.0)
        bucket.refill(fake_time.now())
        
        # Should have refilled to capacity
        assert bucket.tokens == pytest.approx(20.0, abs=0.01)


class TestAdaptiveRate:
    """Test adaptive rate limiting based on headers."""
    
    def test_update_from_headers(self, rate_limiter, sample_request):
        """Test bucket updates from rate limit headers."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        bucket = rate_limiter._get_or_create_bucket(bucket_key)
        
        # Simulate server headers
        bucket.update_from_headers(
            limit=100,
            remaining=50,
            reset=2000.0,  # Reset in future
        )
        
        assert bucket.server_limit == 100
        assert bucket.server_remaining == 50
        assert bucket.server_reset == 2000.0
    
    def test_sync_tokens_with_server(self, rate_limiter, sample_request):
        """Test that local tokens sync with server remaining."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        bucket = rate_limiter._get_or_create_bucket(bucket_key)
        
        # Bucket thinks it has 20 tokens
        assert bucket.tokens == 20.0
        
        # Server says we only have 5 remaining
        bucket.update_from_headers(remaining=5)
        
        # Should sync down to server value
        assert bucket.tokens == 5.0
    
    @pytest.mark.asyncio
    async def test_adaptive_rate_calculation(
        self, rate_limiter, sample_request, fake_time
    ):
        """Test adaptive rate when server provides limits."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        bucket = rate_limiter._get_or_create_bucket(bucket_key)
        
        # Server says: 100 requests remaining, reset in 10 seconds
        bucket.update_from_headers(
            limit=100,
            remaining=100,
            reset=fake_time.now() + 10.0,
        )
        
        # Consume tokens
        bucket.consume(20)
        
        # Refill should use adaptive rate if it's lower than default
        initial_tokens = bucket.tokens
        fake_time.advance(1.0)
        bucket.refill(fake_time.now())
        
        # Should have refilled at configured rate (10 tokens/sec)
        # since adaptive rate (100/10 = 10) matches default
        assert bucket.tokens == pytest.approx(initial_tokens + 10.0, abs=0.5)


class TestRetryLogic:
    """Test 429 and 5xx retry handling."""
    
    def test_429_with_retry_after_header(self, rate_limiter, sample_request):
        """Test 429 response with Retry-After header."""
        headers = {"Retry-After": "5"}
        
        response = rate_limiter.handle_response(
            sample_request,
            status_code=429,
            headers=headers,
            request_id="test-1",
        )
        
        assert response.should_retry is True
        assert response.wait_time == 5.0
        assert "429" in response.reason
    
    def test_429_without_retry_after(self, rate_limiter, sample_request):
        """Test 429 response without Retry-After (exponential backoff)."""
        response = rate_limiter.handle_response(
            sample_request,
            status_code=429,
            headers={},
            request_id="test-2",
        )
        
        assert response.should_retry is True
        # Should use exponential backoff (1 * 2^0 = 1.0 ± jitter)
        assert 0.9 <= response.wait_time <= 1.2
    
    def test_429_max_retries(self, rate_limiter, sample_request):
        """Test 429 stops retrying after max attempts."""
        request_id = "test-3"
        
        # Exhaust retries
        for i in range(RateLimiter.MAX_RETRIES_429):
            response = rate_limiter.handle_response(
                sample_request,
                status_code=429,
                headers={},
                request_id=request_id,
            )
            assert response.should_retry is True
        
        # Next attempt should fail
        response = rate_limiter.handle_response(
            sample_request,
            status_code=429,
            headers={},
            request_id=request_id,
        )
        
        assert response.should_retry is False
        assert "Max 429 retries" in response.reason
    
    def test_5xx_exponential_backoff(self, rate_limiter, sample_request):
        """Test 5xx response uses exponential backoff."""
        request_id = "test-4"
        
        # First retry
        response1 = rate_limiter.handle_response(
            sample_request,
            status_code=503,
            headers={},
            request_id=request_id,
        )
        assert response1.should_retry is True
        backoff1 = response1.wait_time
        
        # Second retry (should be longer)
        response2 = rate_limiter.handle_response(
            sample_request,
            status_code=503,
            headers={},
            request_id=request_id,
        )
        assert response2.should_retry is True
        backoff2 = response2.wait_time
        
        # Second backoff should be roughly 2x first (allowing for jitter)
        assert backoff2 > backoff1
    
    def test_5xx_max_retries(self, rate_limiter, sample_request):
        """Test 5xx stops retrying after max attempts."""
        request_id = "test-5"
        
        # Exhaust retries
        for i in range(RateLimiter.MAX_RETRIES_5XX):
            response = rate_limiter.handle_response(
                sample_request,
                status_code=500,
                headers={},
                request_id=request_id,
            )
            assert response.should_retry is True
        
        # Next attempt should fail
        response = rate_limiter.handle_response(
            sample_request,
            status_code=500,
            headers={},
            request_id=request_id,
        )
        
        assert response.should_retry is False
        assert "Max 5xx retries" in response.reason
    
    def test_success_clears_retry_count(self, rate_limiter, sample_request):
        """Test successful response clears retry tracking."""
        request_id = "test-6"
        
        # Trigger a retry
        rate_limiter.handle_response(
            sample_request,
            status_code=429,
            headers={},
            request_id=request_id,
        )
        
        assert request_id in rate_limiter.retry_counts
        
        # Success should clear
        rate_limiter.handle_response(
            sample_request,
            status_code=200,
            headers={},
            request_id=request_id,
        )
        
        assert request_id not in rate_limiter.retry_counts
    
    def test_parse_retry_after_http_date(self, rate_limiter):
        """Test parsing HTTP-date format in Retry-After."""
        # Example HTTP-date format
        retry_after = "Wed, 21 Oct 2015 07:28:00 GMT"
        
        # Should parse without error (exact value depends on current time)
        wait_time = rate_limiter._parse_retry_after(retry_after)
        assert isinstance(wait_time, float)
        assert wait_time >= 0.0


class TestConcurrencyControl:
    """Test concurrency limiting via semaphore."""
    
    @pytest.mark.asyncio
    async def test_max_concurrent_requests(self, rate_limiter, sample_request):
        """Test that max concurrency is enforced."""
        # Start max_concurrency requests without releasing
        tasks = []
        for i in range(rate_limiter.config.max_concurrency):
            task = asyncio.create_task(rate_limiter.acquire(sample_request))
            tasks.append(task)
        
        # Wait for all to acquire
        await asyncio.gather(*tasks)
        
        # Semaphore should be exhausted
        assert rate_limiter.semaphore.locked()
        
        # Release one
        rate_limiter.release(sample_request)
        
        # Should be able to acquire again
        await rate_limiter.acquire(sample_request)
        rate_limiter.release(sample_request)
    
    @pytest.mark.asyncio
    async def test_release_on_error(self, rate_limiter, sample_request, fake_time):
        """Test that semaphore is released on error."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        bucket = rate_limiter._get_or_create_bucket(bucket_key)
        
        # Force an error by making consume raise
        original_consume = bucket.consume
        
        def failing_consume(count=1):
            raise RuntimeError("Test error")
        
        bucket.consume = failing_consume
        
        # Acquire should fail and release semaphore
        with pytest.raises(RuntimeError):
            await rate_limiter.acquire(sample_request)
        
        # Restore original
        bucket.consume = original_consume
        
        # Semaphore should not be locked
        assert not rate_limiter.semaphore.locked()


class TestStatistics:
    """Test statistics tracking."""
    
    @pytest.mark.asyncio
    async def test_request_counting(self, rate_limiter, sample_request):
        """Test that requests are counted."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        
        # Make some requests
        for i in range(5):
            await rate_limiter.acquire(sample_request)
            rate_limiter.release(sample_request)
        
        stats = rate_limiter.get_stats(bucket_key)[bucket_key]
        assert stats.requests_made == 5
    
    @pytest.mark.asyncio
    async def test_throttle_counting(self, rate_limiter, sample_request, fake_time):
        """Test that throttled requests are counted."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        
        # Exhaust burst
        for i in range(20):
            await rate_limiter.acquire(sample_request)
            rate_limiter.release(sample_request)
        
        # Next request will be throttled
        await rate_limiter.acquire(sample_request)
        rate_limiter.release(sample_request)
        
        stats = rate_limiter.get_stats(bucket_key)[bucket_key]
        assert stats.requests_throttled > 0
    
    def test_retry_counting(self, rate_limiter, sample_request):
        """Test that retries are counted separately."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        
        # Trigger 429 retries
        for i in range(2):
            rate_limiter.handle_response(
                sample_request,
                status_code=429,
                headers={},
                request_id=f"429-{i}",
            )
        
        # Trigger 5xx retries
        for i in range(3):
            rate_limiter.handle_response(
                sample_request,
                status_code=500,
                headers={},
                request_id=f"5xx-{i}",
            )
        
        stats = rate_limiter.get_stats(bucket_key)[bucket_key]
        assert stats.retries_429 == 2
        assert stats.retries_5xx == 3
    
    @pytest.mark.asyncio
    async def test_recent_rate_calculation(
        self, rate_limiter, sample_request, fake_time
    ):
        """Test calculation of recent request rate."""
        bucket_key = rate_limiter._get_bucket_key(sample_request)
        
        # Make 10 requests over 1 second
        for i in range(10):
            await rate_limiter.acquire(sample_request)
            rate_limiter.release(sample_request)
            fake_time.advance(0.1)
        
        stats = rate_limiter.get_stats(bucket_key)[bucket_key]
        recent_rate = stats.get_recent_rate(window_seconds=2.0, current_time=fake_time.now())
        
        # Should be around 10 requests/sec
        assert 8.0 <= recent_rate <= 12.0


class TestHeaderParsing:
    """Test parsing of various rate limit headers."""
    
    def test_parse_standard_headers(self, rate_limiter):
        """Test parsing standard X-RateLimit-* headers."""
        headers = {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "75",
            "X-RateLimit-Reset": "1234567890",
        }
        
        limit, remaining, reset = rate_limiter._parse_rate_limit_headers(headers)
        
        assert limit == 100
        assert remaining == 75
        assert reset == 1234567890.0
    
    def test_parse_custom_header_names(self):
        """Test parsing with custom header names from config."""
        config = ExchangeConfig(
            host="api.example.com",
            steady_rate=10.0,
            burst=20,
            max_concurrency=4,
        )
        config.headers.limit = "Rate-Limit"
        config.headers.remaining = "Rate-Remaining"
        config.headers.reset = "Rate-Reset"
        
        limiter = RateLimiter(config)
        
        headers = {
            "Rate-Limit": "50",
            "Rate-Remaining": "25",
            "Rate-Reset": "9999999",
        }
        
        limit, remaining, reset = limiter._parse_rate_limit_headers(headers)
        
        assert limit == 50
        assert remaining == 25
        assert reset == 9999999.0
    
    def test_parse_missing_headers(self, rate_limiter):
        """Test parsing when headers are missing."""
        limit, remaining, reset = rate_limiter._parse_rate_limit_headers({})
        
        assert limit is None
        assert remaining is None
        assert reset is None
    
    def test_parse_invalid_header_values(self, rate_limiter):
        """Test parsing handles invalid header values gracefully."""
        headers = {
            "X-RateLimit-Limit": "not-a-number",
            "X-RateLimit-Remaining": "invalid",
            "X-RateLimit-Reset": "bad-timestamp",
        }
        
        limit, remaining, reset = rate_limiter._parse_rate_limit_headers(headers)
        
        # Should return None for invalid values
        assert limit is None
        assert remaining is None
        assert reset is None


class TestBucketKeying:
    """Test bucket key generation."""
    
    def test_same_host_same_bucket(self, rate_limiter):
        """Test requests to same host share bucket."""
        req1 = RequestSpec(url="https://api.example.com/markets", method="GET")
        req2 = RequestSpec(url="https://api.example.com/orders", method="GET")
        
        key1 = rate_limiter._get_bucket_key(req1)
        key2 = rate_limiter._get_bucket_key(req2)
        
        assert key1 == key2
    
    def test_different_host_different_bucket(self, rate_limiter):
        """Test requests to different hosts use different buckets."""
        req1 = RequestSpec(url="https://api.example.com/markets", method="GET")
        req2 = RequestSpec(url="https://api.other.com/markets", method="GET")
        
        key1 = rate_limiter._get_bucket_key(req1)
        key2 = rate_limiter._get_bucket_key(req2)
        
        assert key1 != key2


