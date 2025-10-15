"""
Integration tests for rate limiter using stub server.
[CTX:PBI-0:0-4:STUB]

Tests verify rate limiter behavior against a real HTTP server with configurable
responses simulating various API conditions.

Test scenarios:
1. Steady requests under limit → no sleeps triggered
2. Burst causing 429 → limiter honors Retry-After then resumes
3. Alternating 5xx → bounded retries, eventual success/fail
4. Header-based adaptation → limiter adjusts rate dynamically
"""
import asyncio
import logging

import pytest
from aiohttp import ClientSession, ClientTimeout

from pred_mkts.core.config import ExchangeConfig
from pred_mkts.core.datasource import RequestSpec
from pred_mkts.core.rate_limiter import FakeTimeProvider, RateLimiter

from .stub_server import (
    StubServer,
    error_response,
    exhausted_response,
    success_response,
    throttle_response,
)

logger = logging.getLogger(__name__)


# [CTX:PBI-0:0-4:STUB] Fixtures
@pytest.fixture
async def stub_server():
    """Provide stub server for integration tests."""
    server = StubServer(host="127.0.0.1", port=8889)
    await server.start()
    
    yield server
    
    await server.stop()


@pytest.fixture
def fake_time():
    """Provide fake time provider."""
    return FakeTimeProvider(initial_time=1000.0)


@pytest.fixture
def exchange_config(stub_server):
    """Provide exchange config pointing to stub server."""
    return ExchangeConfig(
        host="127.0.0.1:8889",
        steady_rate=10,  # 10 requests/sec
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
def rate_limiter(exchange_config, fake_time):
    """Provide rate limiter with fake time."""
    return RateLimiter(
        exchange_config=exchange_config,
        time_provider=fake_time
    )


def make_request_spec(stub_server, path="/api/test"):
    """Create request spec for stub server."""
    return RequestSpec(
        url=stub_server.get_url(path),
        method="GET",
        headers={},
        query_params={}
    )


# [CTX:PBI-0:0-4:STUB] Scenario 1: Steady requests under limit
@pytest.mark.asyncio
class TestSteadyRequests:
    """Test steady request patterns that stay under rate limit."""
    
    async def test_under_limit_no_throttling(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Scenario 1: Steady requests under limit → no sleeps triggered.
        
        Make requests within burst capacity, verify no throttling occurs.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # Configure stub to return success for all requests
        for i in range(15):
            stub_server.enqueue_response(success_response(
                limit=100,
                remaining=100 - i,
                reset_offset=60
            ))
        
        request_spec = make_request_spec(stub_server)
        
        # Make 15 requests (under burst capacity of 20)
        total_wait = 0.0
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            for _ in range(15):
                async with rate_limiter.acquire_async(request_spec) as guard:
                    total_wait += guard.wait_time
                    
                    # Make actual HTTP request
                    async with session.get(request_spec.url) as response:
                        assert response.status == 200
                        
                        # Process response headers
                        headers = {k: v for k, v in response.headers.items()}
                        wait_time = rate_limiter.handle_response_headers(
                            request_spec,
                            headers,
                            response.status
                        )
                        assert wait_time is None  # No throttling
        
        # Verify no throttling occurred
        stats = rate_limiter.get_stats()
        assert stats.requests_total == 15
        assert stats.requests_throttled == 0
        assert total_wait == 0.0
        
        # Verify all requests were made
        assert stub_server.request_count == 15
    
    async def test_burst_capacity(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Test that burst capacity allows immediate requests up to limit.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # Configure stub for burst capacity (20 requests)
        for i in range(20):
            stub_server.enqueue_response(success_response(
                limit=100,
                remaining=100 - i,
                reset_offset=60
            ))
        
        request_spec = make_request_spec(stub_server)
        
        # Make 20 immediate requests (exactly burst capacity)
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            for _ in range(20):
                async with rate_limiter.acquire_async(request_spec) as guard:
                    assert guard.wait_time == 0.0  # No wait for burst
                    
                    async with session.get(request_spec.url) as response:
                        assert response.status == 200
        
        stats = rate_limiter.get_stats()
        assert stats.requests_total == 20
        assert stats.requests_throttled == 0


# [CTX:PBI-0:0-4:STUB] Scenario 2: 429 handling
@pytest.mark.asyncio
class TestThrottleHandling:
    """Test 429 throttle response handling."""
    
    async def test_429_with_retry_after(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Scenario 2: Burst causing 429 → limiter honors Retry-After then resumes.
        
        Make requests, receive 429, verify limiter respects Retry-After header.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # Configure stub: success, then 429, then success again
        stub_server.enqueue_response(success_response())
        stub_server.enqueue_response(throttle_response(retry_after=10))
        stub_server.enqueue_response(success_response())
        
        request_spec = make_request_spec(stub_server)
        
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            # First request: success
            async with rate_limiter.acquire_async(request_spec):
                async with session.get(request_spec.url) as response:
                    assert response.status == 200
            
            # Second request: 429
            async with rate_limiter.acquire_async(request_spec):
                async with session.get(request_spec.url) as response:
                    assert response.status == 429
                    
                    headers = {k: v for k, v in response.headers.items()}
                    wait_time = rate_limiter.handle_response_headers(
                        request_spec,
                        headers,
                        response.status
                    )
                    
                    # Should return wait time from Retry-After
                    assert wait_time == 10.0
                    
                    # Should indicate retry is needed
                    assert rate_limiter.should_retry(response.status, 0)
            
            # Simulate waiting (advance fake time)
            fake_time.advance(10.0)
            
            # Third request: success after waiting
            async with rate_limiter.acquire_async(request_spec):
                async with session.get(request_spec.url) as response:
                    assert response.status == 200
        
        # Verify 429 was tracked
        stats = rate_limiter.get_stats()
        assert stats.requests_429 == 1
        assert stats.requests_total == 3
    
    async def test_429_without_retry_after(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Test 429 without Retry-After header uses exponential backoff.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # 429 without Retry-After header - create minimal response
        from tests.integration.stub_server import StubResponse
        stub_server.enqueue_response(StubResponse(
            status=429,
            headers={},  # No Retry-After, no rate limit headers
            body='{"error": "Rate limit exceeded"}'
        ))
        
        request_spec = make_request_spec(stub_server)
        
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with rate_limiter.acquire_async(request_spec):
                async with session.get(request_spec.url) as response:
                    assert response.status == 429
                    
                    headers = {k: v for k, v in response.headers.items()}
                    wait_time = rate_limiter.handle_response_headers(
                        request_spec,
                        headers,
                        response.status
                    )
                    
                    # Should use exponential backoff (base 1.0 with jitter)
                    assert wait_time is not None
                    assert 0.75 <= wait_time <= 1.5
    
    async def test_exhausted_rate_limit(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Test handling of rate limit exhaustion (remaining=0).
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # Response indicates rate limit exhausted
        stub_server.enqueue_response(exhausted_response(reset_offset=20))
        
        request_spec = make_request_spec(stub_server)
        
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with rate_limiter.acquire_async(request_spec):
                async with session.get(request_spec.url) as response:
                    assert response.status == 200
                    
                    headers = {k: v for k, v in response.headers.items()}
                    wait_time = rate_limiter.handle_response_headers(
                        request_spec,
                        headers,
                        response.status
                    )
                    
                    # Should wait until reset time
                    assert wait_time == pytest.approx(20.0)
        
        stats = rate_limiter.get_stats()
        assert stats.requests_throttled == 1


# [CTX:PBI-0:0-4:STUB] Scenario 3: 5xx error handling
@pytest.mark.asyncio
class TestErrorHandling:
    """Test 5xx error response handling with retries."""
    
    async def test_5xx_with_retry(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Scenario 3: Alternating 5xx → bounded retries, eventual success.
        
        Simulate 5xx errors with retries until success.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # Configure stub: 500, 500, then success
        stub_server.enqueue_response(error_response(500))
        stub_server.enqueue_response(error_response(500))
        stub_server.enqueue_response(success_response())
        
        request_spec = make_request_spec(stub_server)
        
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            attempt = 0
            success = False
            
            while attempt < 4 and not success:
                async with rate_limiter.acquire_async(request_spec):
                    async with session.get(request_spec.url) as response:
                        if response.status == 500:
                            headers = {k: v for k, v in response.headers.items()}
                            wait_time = rate_limiter.handle_response_headers(
                                request_spec,
                                headers,
                                response.status
                            )
                            
                            # Should use backoff for 5xx
                            assert wait_time is not None
                            assert wait_time > 0
                            
                            # Check if should retry
                            should_retry = rate_limiter.should_retry(
                                response.status,
                                attempt,
                                "GET"
                            )
                            
                            if should_retry:
                                # Simulate waiting
                                fake_time.advance(wait_time)
                                attempt += 1
                            else:
                                break
                        else:
                            success = True
            
            assert success
            assert attempt == 2  # 2 failures before success
        
        stats = rate_limiter.get_stats()
        assert stats.requests_5xx == 2
        assert stats.requests_total == 3
    
    async def test_5xx_max_retries(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Test that 5xx retries are bounded at max attempts.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # Configure stub: all 503 errors
        for _ in range(10):
            stub_server.enqueue_response(error_response(503))
        
        request_spec = make_request_spec(stub_server)
        
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            attempt = 0
            max_attempts = 4  # Initial + 3 retries
            
            while attempt < max_attempts:
                async with rate_limiter.acquire_async(request_spec):
                    async with session.get(request_spec.url) as response:
                        assert response.status == 503
                        
                        headers = {k: v for k, v in response.headers.items()}
                        wait_time = rate_limiter.handle_response_headers(
                            request_spec,
                            headers,
                            response.status
                        )
                        
                        should_retry = rate_limiter.should_retry(
                            response.status,
                            attempt,
                            "GET"
                        )
                        
                        if not should_retry:
                            break
                        
                        fake_time.advance(wait_time or 1.0)
                        attempt += 1
            
            # Should have stopped after max retries
            assert attempt == 3  # 0, 1, 2 attempts, then stop
        
        stats = rate_limiter.get_stats()
        assert stats.requests_5xx >= 3
    
    async def test_5xx_non_idempotent_no_retry(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Test that 5xx for non-idempotent methods are not retried.
        """
        # POST request should not be retried on 5xx
        should_retry = rate_limiter.should_retry(500, 0, "POST")
        assert should_retry is False
        
        # GET request should be retried
        should_retry = rate_limiter.should_retry(500, 0, "GET")
        assert should_retry is True


# [CTX:PBI-0:0-4:STUB] Scenario 4: Adaptive rate adjustment
@pytest.mark.asyncio
class TestAdaptiveRate:
    """Test adaptive rate adjustment based on server headers."""
    
    async def test_adaptive_rate_increase(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Scenario 4: Header-based adaptation → limiter adjusts rate dynamically.
        
        Server indicates higher rate limit, verify limiter adapts.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # Initial request with standard rate
        stub_server.enqueue_response(success_response(
            limit=100,
            remaining=99,
            reset_offset=60
        ))
        
        request_spec = make_request_spec(stub_server)
        
        # Get initial bucket rate
        bucket = rate_limiter._get_or_create_bucket("127.0.0.1:8889")
        initial_rate = bucket.rate
        assert initial_rate == 10.0  # From config
        
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with rate_limiter.acquire_async(request_spec):
                async with session.get(request_spec.url) as response:
                    assert response.status == 200
                    
                    # Get headers and handle
                    headers = {k: v for k, v in response.headers.items()}
                    rate_limiter.handle_response_headers(
                        request_spec,
                        headers,
                        response.status
                    )
        
        # Now configure server to indicate higher rate
        # 500 requests over 20 seconds = 25 req/sec
        stub_server.enqueue_response(success_response(
            limit=500,
            remaining=499,
            reset_offset=20
        ))
        
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with rate_limiter.acquire_async(request_spec):
                async with session.get(request_spec.url) as response:
                    assert response.status == 200
                    
                    headers = {k: v for k, v in response.headers.items()}
                    # Manually set reset to test adaptive behavior
                    headers["X-RateLimit-Reset"] = str(1020.0)  # 20 sec from fake time
                    
                    rate_limiter.handle_response_headers(
                        request_spec,
                        headers,
                        response.status
                    )
        
        # Verify rate was adjusted
        assert bucket.rate == pytest.approx(25.0)
        
        stats = rate_limiter.get_stats()
        # At least 1 adjustment, possibly 2 depending on initial response
        assert stats.adaptive_adjustments >= 1
    
    async def test_adaptive_rate_decrease(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Test adaptive rate decrease when server lowers limit.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        request_spec = make_request_spec(stub_server)
        bucket = rate_limiter._get_or_create_bucket("127.0.0.1:8889")
        
        # Set initial higher rate
        bucket.rate = 20.0
        
        # Server indicates lower rate: 50 requests over 10 seconds = 5 req/sec
        stub_server.enqueue_response(success_response(
            limit=50,
            remaining=49,
            reset_offset=10
        ))
        
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with rate_limiter.acquire_async(request_spec):
                async with session.get(request_spec.url) as response:
                    headers = {k: v for k, v in response.headers.items()}
                    # Set reset time for testing
                    headers["X-RateLimit-Reset"] = str(1010.0)  # 10 sec from fake time
                    
                    rate_limiter.handle_response_headers(
                        request_spec,
                        headers,
                        response.status
                    )
        
        # Verify rate was decreased
        assert bucket.rate == pytest.approx(5.0)
        assert rate_limiter.get_stats().adaptive_adjustments >= 1


# [CTX:PBI-0:0-4:STUB] Complex integration scenarios
@pytest.mark.asyncio
class TestComplexScenarios:
    """Test complex real-world scenarios."""
    
    async def test_mixed_response_pattern(
        self,
        stub_server,
        rate_limiter,
        fake_time
    ):
        """
        Test complex pattern: success → 429 → success → 500 → success.
        """
        stub_server.clear_queue()
        stub_server.reset_stats()
        
        # Configure mixed pattern
        stub_server.enqueue_response(success_response())
        stub_server.enqueue_response(throttle_response(retry_after=5))
        stub_server.enqueue_response(success_response())
        stub_server.enqueue_response(error_response(500))
        stub_server.enqueue_response(success_response())
        
        request_spec = make_request_spec(stub_server)
        
        results = []
        async with ClientSession(timeout=ClientTimeout(total=10)) as session:
            for i in range(5):
                attempt = 0
                while attempt < 3:
                    async with rate_limiter.acquire_async(request_spec):
                        async with session.get(request_spec.url) as response:
                            results.append(response.status)
                            
                            headers = {k: v for k, v in response.headers.items()}
                            wait_time = rate_limiter.handle_response_headers(
                                request_spec,
                                headers,
                                response.status
                            )
                            
                            if response.status in (429, 500):
                                if rate_limiter.should_retry(response.status, attempt, "GET"):
                                    fake_time.advance(wait_time or 1.0)
                                    attempt += 1
                                    continue
                            
                            break
        
        # Verify all status codes were encountered
        assert 200 in results
        assert 429 in results
        assert 500 in results
        
        stats = rate_limiter.get_stats()
        assert stats.requests_429 >= 1
        assert stats.requests_5xx >= 1

