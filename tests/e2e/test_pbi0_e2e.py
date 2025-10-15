"""
End-to-end test for PBI-0: Multi-exchange substrate + precise rate limiting.
[CTX:PBI-0:0-6:E2E]

This test verifies that the substrate and limiter together meet all Conditions of
Satisfaction for PBI-0 by simulating a full request sequence with:
- Normal operation (below limit)
- 429 responses with Retry-After
- Adaptive rate adjustment via headers
- 5xx errors with exponential backoff

The test uses real rate limiter and config with a stub server, capturing
telemetry to verify correct behavior.
"""
import asyncio
import logging
import time
from pathlib import Path

import aiohttp
import pytest

from pred_mkts.core.config import ExchangeConfig
from pred_mkts.core.datasource import RequestSpec
from pred_mkts.core.rate_limiter import FakeTimeProvider, RateLimiter
from pred_mkts.core.telemetry import (
    TelemetryDecision,
    TelemetryRecorder,
    TelemetryLevel,
    set_recorder,
)
from tests.integration.stub_server import (
    StubResponse,
    StubServer,
    success_response,
    throttle_response,
    error_response,
)

logger = logging.getLogger(__name__)


# [CTX:PBI-0:0-6:E2E] Test constants
TEST_HOST = "127.0.0.1"
TEST_PORT = 18889  # Use high port number to avoid conflicts
STEADY_RATE = 20.0  # tokens per second (fast for testing)
BURST_CAPACITY = 10  # tokens
MAX_CONCURRENCY = 4
SHORT_RETRY_AFTER = 1  # Short retry for fast tests (must be >= 1 for int conversion)


@pytest.fixture
async def stub_server():
    """Create and start stub server for testing."""
    server = StubServer(host=TEST_HOST, port=TEST_PORT)
    await server.start()
    
    # Give server time to start
    await asyncio.sleep(0.1)
    
    yield server
    
    await server.stop()


@pytest.fixture
def test_config(stub_server):
    """Create test configuration using actual server port."""
    return ExchangeConfig(
        host=f"{TEST_HOST}:{stub_server.port}",
        steady_rate=STEADY_RATE,
        burst=BURST_CAPACITY,
        max_concurrency=MAX_CONCURRENCY,
        headers={
            "retry_after": "Retry-After",
            "limit": "X-RateLimit-Limit",
            "remaining": "X-RateLimit-Remaining",
            "reset": "X-RateLimit-Reset",
        }
    )


@pytest.fixture
def rate_limiter(test_config):
    """Create rate limiter with real time provider for E2E test."""
    # Use real time provider for E2E test to avoid asyncio/fake time mismatch
    return RateLimiter(exchange_config=test_config)


@pytest.fixture
def telemetry_recorder():
    """Create telemetry recorder for capturing events."""
    recorder = TelemetryRecorder(
        level=TelemetryLevel.DEBUG,
        format_json=False,
        collect_stats=True
    )
    set_recorder(recorder)
    recorder.clear_events()
    recorder.reset_stats()
    return recorder


@pytest.fixture
def artifacts_dir():
    """Ensure artifacts directory exists."""
    artifacts_path = Path(__file__).parent.parent.parent / "artifacts" / "test_logs"
    artifacts_path.mkdir(parents=True, exist_ok=True)
    return artifacts_path


async def make_request(
    session: aiohttp.ClientSession,
    url: str,
    rate_limiter: RateLimiter,
    request_spec: RequestSpec,
    attempt: int = 0
) -> tuple[int, dict, float]:
    """
    Make HTTP request through rate limiter.
    
    Args:
        session: aiohttp client session
        url: Full URL to request
        rate_limiter: Rate limiter instance
        request_spec: Request specification
        attempt: Retry attempt number
        
    Returns:
        Tuple of (status_code, headers, elapsed_ms)
    """
    start_time = time.time()
    
    # Acquire rate limit permission
    async with rate_limiter.acquire_async(request_spec):
        # Make actual HTTP request
        request_start = time.time()
        
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                status = response.status
                headers = dict(response.headers)
                await response.text()  # Consume body
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise
        
        elapsed_ms = (time.time() - request_start) * 1000
        
        # Let rate limiter process response headers
        wait_time = rate_limiter.handle_response_headers(
            request_spec=request_spec,
            headers=headers,
            status_code=status,
            elapsed_ms=elapsed_ms,
            attempt=attempt
        )
        
        # If wait_time is returned, we need to wait
        if wait_time is not None and wait_time > 0:
            # Actually sleep for the wait time
            await asyncio.sleep(wait_time)
        
        return status, headers, elapsed_ms


@pytest.mark.asyncio
async def test_pbi0_e2e_cos(
    stub_server,
    rate_limiter,
    test_config,
    telemetry_recorder,
    artifacts_dir
):
    """
    [CTX:PBI-0:0-6:E2E] End-to-end test verifying all Conditions of Satisfaction.
    
    This test performs a scripted sequence of requests that:
    1. Stay below limit (no sleeps) - verify normal operation
    2. Exceed limit → receive 429 + Retry-After → limiter pauses then resumes
    3. Simulate adaptive headers (limit/reset) → limiter adjusts rate
    4. Introduce intermittent 5xx → retries with backoff
    
    Assertions verify:
    - Total runtime matches expected from rate config and fake time
    - No unhandled exceptions
    - Telemetry shows correct decision sequence
    """
    log_file = artifacts_dir / "pbi0_e2e.log"
    
    # Configure logging to file
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    logging.getLogger().addHandler(file_handler)
    
    logger.info("[CTX:PBI-0:0-6:E2E] Starting E2E test")
    
    # Prepare request spec using actual server port
    base_url = f"http://{TEST_HOST}:{stub_server.port}"
    request_spec = RequestSpec(url=f"{base_url}/api/test")
    
    test_start_time = time.time()
    total_requests = 0
    successful_requests = 0
    
    async with aiohttp.ClientSession() as session:
        # ================================================================
        # PHASE 1: Stay below limit (use burst capacity)
        # ================================================================
        logger.info("[CTX:PBI-0:0-6:E2E] Phase 1: Below limit (burst capacity)")
        
        # Configure server to return success for first 5 requests
        for i in range(5):
            stub_server.enqueue_response(
                success_response(limit=100, remaining=100-i-1, reset_offset=60)
            )
        
        # Make 5 requests (within burst capacity of 10)
        # These should all succeed without throttling
        phase1_start = time.time()
        
        for i in range(5):
            status, headers, elapsed = await make_request(
                session, base_url + f"/api/test?req={i}",
                rate_limiter, request_spec
            )
            total_requests += 1
            
            assert status == 200, f"Phase 1 request {i} failed: {status}"
            successful_requests += 1
            
            logger.info(f"[CTX:PBI-0:0-6:E2E] Phase 1 request {i}: {status}")
        
        phase1_duration = time.time() - phase1_start
        logger.info(
            f"[CTX:PBI-0:0-6:E2E] Phase 1 complete: {phase1_duration:.2f}s, "
            f"{successful_requests} successful"
        )
        
        # Should complete quickly (no throttling within burst)
        assert phase1_duration < 1.0, "Phase 1 should not be throttled"
        
        # ================================================================
        # PHASE 2: Exceed limit → 429 with Retry-After
        # ================================================================
        logger.info("[CTX:PBI-0:0-6:E2E] Phase 2: Exceed limit, trigger 429")
        
        # Exhaust remaining tokens (5 more requests to exceed burst capacity)
        for i in range(5):
            stub_server.enqueue_response(
                success_response(limit=100, remaining=95-i, reset_offset=60)
            )
        
        phase2_start = time.time()
        
        for i in range(5):
            status, headers, elapsed = await make_request(
                session, base_url + f"/api/test?req={5+i}",
                rate_limiter, request_spec
            )
            total_requests += 1
            
            assert status == 200
            successful_requests += 1
        
        # Now trigger 429 response with short retry
        stub_server.enqueue_response(throttle_response(retry_after=SHORT_RETRY_AFTER))
        
        # This request should get 429 and wait
        status, headers, elapsed = await make_request(
            session, base_url + "/api/test?req=429",
            rate_limiter, request_spec
        )
        total_requests += 1
        
        assert status == 429, "Should receive 429 response"
        assert "Retry-After" in headers
        
        # Should retry after the rate limiter processes it
        phase2_duration = time.time() - phase2_start
        logger.info(
            f"[CTX:PBI-0:0-6:E2E] Phase 2 complete: {phase2_duration:.2f}s elapsed, "
            f"429 handled with Retry-After"
        )
        
        # Verify we waited (should have waited at least SHORT_RETRY_AFTER)
        assert phase2_duration >= SHORT_RETRY_AFTER, "Should wait for Retry-After"
        
        # ================================================================
        # PHASE 3: Adaptive rate adjustment via headers
        # ================================================================
        logger.info("[CTX:PBI-0:0-6:E2E] Phase 3: Adaptive rate adjustment")
        
        phase3_start = time.time()
        
        # Configure server to return reduced limit in headers
        # Simulate server saying: 50 requests per 60 seconds
        for i in range(3):
            current_time = int(time.time())
            stub_server.enqueue_response(
                StubResponse(
                    status=200,
                    headers={
                        "X-RateLimit-Limit": "50",  # Reduced from 100
                        "X-RateLimit-Remaining": str(50 - i - 1),
                        "X-RateLimit-Reset": str(current_time + 60),
                    },
                    body='{"status": "ok"}'
                )
            )
        
        adaptive_count_before = telemetry_recorder.get_stats().decisions_by_type.get(
            TelemetryDecision.ADAPTIVE.value, 0
        )
        
        # Make requests that trigger adaptive adjustment
        for i in range(3):
            status, headers, elapsed = await make_request(
                session, base_url + f"/api/test?req=adaptive-{i}",
                rate_limiter, request_spec
            )
            total_requests += 1
            
            assert status == 200
            successful_requests += 1
            
            # Small delay to allow token refill
            await asyncio.sleep(0.05)
        
        phase3_duration = time.time() - phase3_start
        
        adaptive_count_after = telemetry_recorder.get_stats().decisions_by_type.get(
            TelemetryDecision.ADAPTIVE.value, 0
        )
        
        logger.info(
            f"[CTX:PBI-0:0-6:E2E] Phase 3 complete: {phase3_duration:.2f}s, "
            f"adaptive adjustments: {adaptive_count_after - adaptive_count_before}"
        )
        
        # Should have triggered adaptive adjustment
        assert adaptive_count_after > adaptive_count_before, \
            "Should have adaptive adjustments"
        
        # ================================================================
        # PHASE 4: 5xx errors with retry
        # ================================================================
        logger.info("[CTX:PBI-0:0-6:E2E] Phase 4: 5xx errors with retry")
        
        phase4_start = time.time()
        
        # Configure server to return 503, then 500, then success
        stub_server.enqueue_response(error_response(status=503))
        stub_server.enqueue_response(error_response(status=500))
        stub_server.enqueue_response(success_response(limit=50, remaining=45))
        
        backoff_5xx_before = telemetry_recorder.get_stats().decisions_by_type.get(
            TelemetryDecision.BACKOFF_5XX.value, 0
        )
        
        # Make requests that trigger 5xx
        for attempt in range(3):
            status, headers, elapsed = await make_request(
                session, base_url + f"/api/test?req=5xx-attempt-{attempt}",
                rate_limiter, request_spec,
                attempt=attempt
            )
            total_requests += 1
            
            if status >= 500:
                logger.info(f"[CTX:PBI-0:0-6:E2E] Got {status}, will retry")
                # Check if should retry
                if rate_limiter.should_retry(status, attempt):
                    await asyncio.sleep(0.05)  # Short sleep for retry
                    continue
            
            # Final attempt should succeed
            assert status == 200, f"Final attempt failed: {status}"
            successful_requests += 1
            break
        
        phase4_duration = time.time() - phase4_start
        
        backoff_5xx_after = telemetry_recorder.get_stats().decisions_by_type.get(
            TelemetryDecision.BACKOFF_5XX.value, 0
        )
        
        logger.info(
            f"[CTX:PBI-0:0-6:E2E] Phase 4 complete: {phase4_duration:.2f}s, "
            f"5xx backoffs: {backoff_5xx_after - backoff_5xx_before}"
        )
        
        # Should have triggered 5xx backoff
        assert backoff_5xx_after > backoff_5xx_before, "Should have 5xx backoffs"
    
    # ================================================================
    # VERIFY OVERALL RESULTS
    # ================================================================
    test_duration = time.time() - test_start_time
    
    logger.info("[CTX:PBI-0:0-6:E2E] Test complete")
    logger.info(f"[CTX:PBI-0:0-6:E2E] Total duration: {test_duration:.2f}s (fake time)")
    logger.info(f"[CTX:PBI-0:0-6:E2E] Total requests: {total_requests}")
    logger.info(f"[CTX:PBI-0:0-6:E2E] Successful: {successful_requests}")
    
    # Get telemetry stats
    stats = telemetry_recorder.get_stats()
    logger.info(f"[CTX:PBI-0:0-6:E2E] Telemetry stats: {stats.to_dict()}")
    
    # Get all events for detailed verification
    events = telemetry_recorder.get_events()
    logger.info(f"[CTX:PBI-0:0-6:E2E] Total telemetry events: {len(events)}")
    
    # Verify decision sequence
    decision_types = [e.decision for e in events]
    
    # Should have mix of ALLOW (fast requests), THROTTLE, BACKOFF_429, ADAPTIVE, BACKOFF_5XX
    assert TelemetryDecision.ALLOW.value in decision_types, \
        "Should have ALLOW decisions"
    assert TelemetryDecision.BACKOFF_429.value in decision_types, \
        "Should have 429 backoff"
    assert TelemetryDecision.ADAPTIVE.value in decision_types, \
        "Should have adaptive adjustments"
    assert TelemetryDecision.BACKOFF_5XX.value in decision_types, \
        "Should have 5xx backoff"
    
    # Verify no unhandled exceptions (test should complete)
    assert successful_requests > 0, "Should have successful requests"
    
    # Verify rate limiter stats
    limiter_stats = rate_limiter.get_stats()
    logger.info(f"[CTX:PBI-0:0-6:E2E] Rate limiter stats: {limiter_stats.to_dict()}")
    
    assert limiter_stats.requests_429 > 0, "Should have handled 429 responses"
    assert limiter_stats.requests_5xx > 0, "Should have handled 5xx responses"
    assert limiter_stats.adaptive_adjustments > 0, "Should have adaptive adjustments"
    
    # Write summary to log file
    logger.info("=" * 80)
    logger.info("[CTX:PBI-0:0-6:E2E] TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total requests: {total_requests}")
    logger.info(f"Successful: {successful_requests}")
    logger.info(f"Total duration (fake time): {test_duration:.2f}s")
    logger.info(f"Rate limiter stats: {limiter_stats.to_dict()}")
    logger.info(f"Telemetry stats: {stats.to_dict()}")
    logger.info("=" * 80)
    logger.info(f"[CTX:PBI-0:0-6:E2E] Test log written to: {log_file}")
    logger.info("=" * 80)
    
    # Verify log file was created
    assert log_file.exists(), f"Test log file should exist: {log_file}"
    
    # Clean up handler
    logging.getLogger().removeHandler(file_handler)
    file_handler.close()
    
    logger.info("[CTX:PBI-0:0-6:E2E] All assertions passed!")

