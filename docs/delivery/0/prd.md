# PBI-0: Multi-exchange substrate + precise rate limiting

## Overview
Provide a reusable substrate for all exchanges: a `DataSource` interface (auth, pagination, endpoints) and a precise, header-aware rate limiter that respects server-provided quotas and retry signals.

## Problem Statement
Each exchange has different endpoints and rate policies. A naive fixed QPS causes throttling or under-utilization. We need an adaptive limiter and a thin adapter per exchange so new sources are easy.

## Technical Approach
- `DataSource` interface with minimal surface:
  - `prepare_request(endpoint, params) -> RequestSpec`
  - `paginate(endpoint, params) -> Iterator[Page]`
  - `auth()` (no-op if public)
- Header-aware limiter that:
  - Tracks **per-host** token buckets (burst + steady rate).
  - Reads `Retry-After`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `X-RateLimit-Limit` when present.
  - Adapts the bucket rate or sleeps until reset when needed.
  - Treats 429/5xx with **jittered exponential backoff**, bounded attempts.
- Config file (YAML) for per-exchange policies:
  - Default steady/burst, max concurrency, endpoints that share buckets.
  - Header field names (override if non-standard).
- Telemetry: structured logs of requests (status, durations, headers seen, limiter decisions).

## Acceptance Criteria
- Pluggable `DataSource` interface with an example stub (Polymarket).
- Limiter honors `Retry-After` and backs off on 429; recovers automatically.
- If headers expose quotas, limiter **adapts** without hardcoding QPS.
- Configurable defaults when headers aren’t present.
- Basic unit/integration tests with a stub server simulating 429/reset headers.

## Dependencies
None externally (start with a local stub server for tests).

## Related Tasks
See `./tasks.md`.
