# Rate Limiting & Telemetry Runbook
<!-- [CTX:PBI-0:0-5:TELEM] -->

This document explains how to configure, monitor, and debug rate limiting behavior in the pred-mkts system.

## Table of Contents

- [Overview](#overview)
- [Configuration](#configuration)
- [Telemetry Fields](#telemetry-fields)
- [Exchange-Specific Patterns](#exchange-specific-patterns)
- [Reading Telemetry Logs](#reading-telemetry-logs)
- [Tuning Configuration](#tuning-configuration)
- [Common Scenarios](#common-scenarios)
- [Troubleshooting](#troubleshooting)

---

## Overview

The rate limiter uses a **token bucket algorithm** with the following features:

- **Per-host token buckets**: Separate rate limits for each exchange
- **Adaptive rate adjustment**: Dynamically adjusts based on `X-RateLimit-*` headers
- **Automatic retry**: Handles 429 and 5xx responses with exponential backoff
- **Concurrency control**: Semaphore-based limiting of concurrent requests
- **Structured telemetry**: JSON or key=value logs for monitoring

### Key Components

1. **TokenBucket**: Maintains token inventory and refill logic
2. **RateLimiter**: Manages buckets, handles responses, emits telemetry
3. **TelemetryRecorder**: Collects and logs rate limiter decisions

---

## Configuration

Rate limits are configured per exchange in `config/limits.yml`:

```yaml
exchanges:
  polymarket:
    host: api.polymarket.com
    steady_rate: 10      # tokens/sec (default rate)
    burst: 20            # max burst capacity
    max_concurrency: 4   # max concurrent requests
    headers:
      retry_after: Retry-After
      limit: X-RateLimit-Limit
      remaining: X-RateLimit-Remaining
      reset: X-RateLimit-Reset
    buckets:
      - key: "global"
        pattern: "/v{1,}/.*"
        share_with: ["orders", "markets"]
```

### Configuration Parameters

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `host` | API hostname | `api.polymarket.com` |
| `steady_rate` | Tokens per second | 5-20 for public APIs |
| `burst` | Maximum burst size | 2-4x steady_rate |
| `max_concurrency` | Concurrent request limit | 2-10 |
| `headers.*` | Rate limit header names | See exchange-specific patterns |

---

## Telemetry Fields

Each telemetry event contains the following structured fields:

### Core Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `timestamp` | ISO 8601 string | Event timestamp (UTC) | `2025-10-15T09:05:00.123Z` |
| `exchange` | string | Exchange/host name | `api.polymarket.com` |
| `endpoint` | string | Full API endpoint URL | `https://api.polymarket.com/markets` |
| `status` | int or null | HTTP status code | `200`, `429`, `500`, `null` |
| `elapsed_ms` | float | Request duration (ms) | `234.5` |
| `decision` | string | Rate limiter decision | See [Decision Types](#decision-types) |
| `sleep_s` | float | Time slept due to rate limit | `1.5` |
| `headers_seen` | object | Relevant rate limit headers | `{"X-RateLimit-Remaining": "10"}` |
| `bucket_key` | string | Bucket identifier | `api.polymarket.com` |
| `attempt` | int | Retry attempt number | `0`, `1`, `2` |
| `tokens_available` | float | Tokens in bucket after event | `15.3` |

### Decision Types

| Decision | Meaning |
|----------|---------|
| `allow` | Request allowed immediately without throttling |
| `throttle` | Request delayed due to insufficient tokens |
| `backoff_429` | Backing off due to 429 Too Many Requests |
| `backoff_5xx` | Backing off due to 5xx server error |
| `adaptive` | Rate adjusted based on server headers |

---

## Exchange-Specific Patterns

### Polymarket

**Rate Limit Headers:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1729000000
Retry-After: 60
```

**Typical Configuration:**
```yaml
polymarket:
  steady_rate: 10
  burst: 20
  max_concurrency: 4
```

**Common Patterns:**
- Reset timestamp is Unix epoch (seconds)
- 429 responses include `Retry-After` header
- Limit typically 100-1000 requests per window

### Kalshi

**Rate Limit Headers:**
```
X-RateLimit-Limit: 50
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1729000000
```

**Typical Configuration:**
```yaml
kalshi:
  steady_rate: 5
  burst: 10
  max_concurrency: 2
```

**Common Patterns:**
- More conservative limits (50-100 requests)
- Reset window typically 60 seconds
- Stricter enforcement on public endpoints

---

## Reading Telemetry Logs

### JSON Format (Default)

```json
{
  "timestamp": "2025-10-15T09:05:00.123Z",
  "exchange": "api.polymarket.com",
  "endpoint": "https://api.polymarket.com/markets",
  "status": 200,
  "elapsed_ms": 234.5,
  "decision": "allow",
  "sleep_s": 0.0,
  "headers_seen": {
    "X-RateLimit-Limit": "100",
    "X-RateLimit-Remaining": "95",
    "X-RateLimit-Reset": "1729000000"
  },
  "bucket_key": "api.polymarket.com",
  "attempt": 0,
  "tokens_available": 15.3
}
```

### Key=Value Format

```
timestamp=2025-10-15T09:05:00.123Z exchange=api.polymarket.com endpoint=https://api.polymarket.com/markets status=200 elapsed_ms=234.5 decision=allow sleep_s=0.0 headers_seen.X-RateLimit-Limit=100 headers_seen.X-RateLimit-Remaining=95 bucket_key=api.polymarket.com attempt=0 tokens_available=15.3
```

### Filtering Logs

**Find all throttling events:**
```bash
grep 'decision.*throttle' logs/app.log | jq .
```

**Find 429 responses:**
```bash
grep 'status.*429' logs/app.log | jq .
```

**Calculate average sleep time:**
```bash
grep 'sleep_s' logs/app.log | jq -r '.sleep_s' | awk '{sum+=$1} END {print sum/NR}'
```

**Find adaptive adjustments:**
```bash
grep 'decision.*adaptive' logs/app.log | jq .
```

---

## Tuning Configuration

### Problem: Too Many 429 Responses

**Symptoms:**
- Frequent `decision=backoff_429` events
- High `requests_429` count in stats
- Consistent sleep times

**Solution:**
1. **Lower `steady_rate`**: Reduce tokens/sec by 20-30%
2. **Check burst capacity**: Ensure `burst` >= 2x `steady_rate`
3. **Add concurrency limit**: Reduce `max_concurrency`

**Example adjustment:**
```yaml
# Before
steady_rate: 10
burst: 20
max_concurrency: 8

# After
steady_rate: 7
burst: 15
max_concurrency: 4
```

### Problem: Slow Response Times

**Symptoms:**
- High `elapsed_ms` values
- Low `tokens_available` counts
- Frequent `decision=throttle` events

**Solution:**
1. **Increase concurrency**: Raise `max_concurrency` carefully
2. **Check burst capacity**: Increase `burst` for traffic spikes
3. **Monitor adaptive adjustments**: Watch for `decision=adaptive`

### Problem: Rate Limit Exhaustion

**Symptoms:**
- `headers_seen.X-RateLimit-Remaining` approaches 0
- Long sleep times before reset
- `decision=throttle` with high `sleep_s`

**Solution:**
1. **Match server limits**: Adjust `steady_rate` to match `X-RateLimit-Limit / window_seconds`
2. **Enable adaptive mode**: Rate limiter will auto-adjust based on headers
3. **Add padding**: Set `steady_rate` to 80-90% of server limit

**Calculation example:**
```
Server limit: 100 requests / 60 seconds
Optimal rate: (100 / 60) * 0.85 = 1.42 tokens/sec
```

### Problem: Adaptive Adjustments Unstable

**Symptoms:**
- Frequent `decision=adaptive` events
- Rate fluctuates wildly
- `tokens_available` varies significantly

**Solution:**
1. **Increase adjustment threshold**: Requires code change to `_apply_adaptive_rate`
2. **Use fixed rate**: Set explicit `steady_rate` if server limits are known
3. **Smooth adjustments**: Consider moving average of observed limits

---

## Common Scenarios

### Scenario 1: Initial API Integration

**Goal**: Establish baseline rate limits

**Steps**:
1. Set conservative initial limits:
   ```yaml
   steady_rate: 5
   burst: 10
   max_concurrency: 2
   ```

2. Monitor telemetry for 24 hours:
   ```bash
   grep '[CTX:PBI-0:0-5:TELEM]' logs/app.log | jq -s '.'
   ```

3. Look for:
   - Average `tokens_available`
   - Frequency of `decision=throttle`
   - Presence of `status=429`

4. Adjust upward if:
   - `tokens_available` consistently > 50% capacity
   - No 429 responses observed
   - `elapsed_ms` is low

### Scenario 2: Handling Rate Limit Changes

**Situation**: Exchange reduces rate limits without notice

**Detection**:
```bash
# Sudden increase in 429s
grep 'status.*429' logs/app.log | wc -l

# Adaptive adjustments lowering rate
grep 'Adaptive rate adjustment.*->' logs/app.log
```

**Response**:
1. Check latest telemetry for new limits:
   ```bash
   grep 'headers_seen' logs/app.log | tail -10 | jq '.headers_seen'
   ```

2. Update configuration to match:
   ```yaml
   # Old limit: 100/60s = 1.67/s
   # New limit: 50/60s = 0.83/s
   steady_rate: 0.7  # 85% of new limit
   ```

3. Monitor for 1 hour to confirm stabilization

### Scenario 3: Debugging Unexpected Delays

**Problem**: Requests taking longer than expected

**Investigation**:
1. Check if rate limiting is the cause:
   ```bash
   grep 'sleep_s' logs/app.log | jq '{endpoint, sleep_s, tokens_available}'
   ```

2. Look for patterns:
   - **High sleep_s**: Rate limit is active
   - **Low tokens_available**: Token bucket depleted
   - **429 or 5xx status**: Server-side throttling

3. Distinguish between:
   - **Rate limit delay**: `sleep_s > 0`
   - **Network delay**: High `elapsed_ms` with `sleep_s = 0`
   - **Server delay**: High `elapsed_ms` with `status = 200`

### Scenario 4: Optimizing for Burst Traffic

**Goal**: Handle periodic traffic spikes without 429s

**Strategy**:
1. Identify spike patterns:
   ```bash
   grep '[CTX:PBI-0:0-5:TELEM]' logs/app.log | \
     jq -r '[.timestamp, .decision] | @csv' | \
     cut -d',' -f1 | cut -d'T' -f2 | cut -d':' -f1 | sort | uniq -c
   ```

2. Calculate required burst capacity:
   ```
   Peak requests in 10s = 30
   Burst capacity needed = 30 (immediate) + (10 * steady_rate) (refill)
   ```

3. Update configuration:
   ```yaml
   steady_rate: 5     # matches sustainable rate
   burst: 35          # handles spike + refill
   ```

---

## Troubleshooting

### Issue: Telemetry Not Appearing

**Check 1: Logging level**
```python
import logging
logging.getLogger('pred_mkts.core.rate_limiter').setLevel(logging.DEBUG)
logging.getLogger('pred_mkts.core.telemetry').setLevel(logging.DEBUG)
```

**Check 2: Recorder configured**
```python
from pred_mkts.core.telemetry import get_recorder, TelemetryLevel

recorder = get_recorder()
recorder.level = TelemetryLevel.DEBUG
```

**Check 3: Grep anchor**
```bash
grep '\[CTX:PBI-0:0-5:TELEM\]' logs/app.log
```

### Issue: Incorrect Sleep Times

**Symptom**: `sleep_s` doesn't match actual delay

**Cause**: Time provider mismatch or concurrent operations

**Debug**:
```python
# Check token bucket state
limiter = get_rate_limiter()
stats = limiter.get_stats()
print(stats.to_dict())
```

### Issue: Adaptive Rate Not Adjusting

**Symptom**: Rate stays fixed despite headers indicating different limit

**Check 1: Headers present**
```bash
grep 'headers_seen' logs/app.log | jq '.headers_seen'
```

**Check 2: Adjustment threshold**
Rate only adjusts if difference > 10%. For small changes, this is expected.

**Check 3: Reset timing**
If `X-RateLimit-Reset` is in the past, adjustment won't trigger.

### Issue: Statistics Drift

**Symptom**: Telemetry stats don't match `RateLimiterStats`

**Cause**: Separate tracking mechanisms

**Solution**: Use telemetry stats for debugging:
```python
recorder = get_recorder()
stats = recorder.get_stats()
print(stats.to_dict())
```

---

## Example Telemetry Snippets

### Successful Request (No Throttling)

```json
{
  "timestamp": "2025-10-15T09:05:00.123Z",
  "exchange": "api.polymarket.com",
  "endpoint": "https://api.polymarket.com/markets",
  "status": null,
  "elapsed_ms": 0.0,
  "decision": "allow",
  "sleep_s": 0.0,
  "headers_seen": {},
  "bucket_key": "api.polymarket.com",
  "attempt": 0,
  "tokens_available": 18.7
}
```

### Throttled Request

```json
{
  "timestamp": "2025-10-15T09:05:02.456Z",
  "exchange": "api.polymarket.com",
  "endpoint": "https://api.polymarket.com/markets",
  "status": null,
  "elapsed_ms": 0.0,
  "decision": "throttle",
  "sleep_s": 0.5,
  "headers_seen": {},
  "bucket_key": "api.polymarket.com",
  "attempt": 0,
  "tokens_available": 19.2
}
```

### 429 Response with Retry-After

```json
{
  "timestamp": "2025-10-15T09:05:05.789Z",
  "exchange": "api.polymarket.com",
  "endpoint": "https://api.polymarket.com/markets",
  "status": 429,
  "elapsed_ms": 145.3,
  "decision": "backoff_429",
  "sleep_s": 60.0,
  "headers_seen": {
    "Retry-After": "60",
    "X-RateLimit-Limit": "100",
    "X-RateLimit-Remaining": "0",
    "X-RateLimit-Reset": "1729000060"
  },
  "bucket_key": "api.polymarket.com",
  "attempt": 0,
  "tokens_available": 18.7
}
```

### Adaptive Rate Adjustment

```json
{
  "timestamp": "2025-10-15T09:05:10.012Z",
  "exchange": "api.polymarket.com",
  "endpoint": "https://api.polymarket.com/markets",
  "status": 200,
  "elapsed_ms": 234.5,
  "decision": "adaptive",
  "sleep_s": 0.0,
  "headers_seen": {
    "X-RateLimit-Limit": "150",
    "X-RateLimit-Remaining": "145",
    "X-RateLimit-Reset": "1729000070"
  },
  "bucket_key": "api.polymarket.com",
  "attempt": 0,
  "tokens_available": 17.9
}
```

### 5xx Error with Backoff

```json
{
  "timestamp": "2025-10-15T09:05:15.345Z",
  "exchange": "api.polymarket.com",
  "endpoint": "https://api.polymarket.com/markets",
  "status": 503,
  "elapsed_ms": 3012.1,
  "decision": "backoff_5xx",
  "sleep_s": 1.0,
  "headers_seen": {},
  "bucket_key": "api.polymarket.com",
  "attempt": 1,
  "tokens_available": 16.8
}
```

---

## Programmatic Access

### Get Telemetry Statistics

```python
from pred_mkts.core.telemetry import get_recorder

recorder = get_recorder()
stats = recorder.get_stats()

print(f"Total requests: {stats.total_requests}")
print(f"Total sleeps: {stats.total_sleeps}")
print(f"Average latency: {stats.to_dict()['avg_latency_ms']}ms")
print(f"Decisions: {stats.decisions_by_type}")
print(f"Status codes: {stats.status_codes}")
```

### Configure Telemetry for Testing

```python
from pred_mkts.core.telemetry import TelemetryRecorder, TelemetryLevel, set_recorder

# Create recorder with stats collection enabled
recorder = TelemetryRecorder(
    level=TelemetryLevel.DEBUG,
    format_json=True,
    collect_stats=True
)

# Set as global recorder
set_recorder(recorder)

# Run your code...

# Check stats
stats = recorder.get_stats()
assert stats.total_sleeps == 0  # No throttling occurred
```

---

## References

- **Source Code**: `src/pred_mkts/core/telemetry.py`
- **Rate Limiter**: `src/pred_mkts/core/rate_limiter.py`
- **Configuration**: `config/limits.yml`
- **Tests**: `tests/unit/test_telemetry.py`

## Grep Anchors

All telemetry logs include the anchor: `[CTX:PBI-0:0-5:TELEM]`

Search examples:
```bash
# All telemetry events
grep '\[CTX:PBI-0:0-5:TELEM\]' logs/app.log

# Rate limiter logs
grep '\[CTX:PBI-0:0-3:RL\]' logs/app.log

# Combined rate limiter and telemetry
grep -E '\[CTX:PBI-0:0-(3|5):(RL|TELEM)\]' logs/app.log
```

