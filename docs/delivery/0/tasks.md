# Tasks for PBI 0: Multi-exchange substrate + precise rate limiting
This document lists all tasks associated with PBI 0.

**Parent PBI**: [PBI 0](./prd.md)

## Task Summary
| Task ID | Name | Status | Description |
| :------ | :--- | :----- | :---------- |
| 0-1 | [Define `DataSource` interface + request spec](./0-1.md) | Done | Interface for exchanges; RequestSpec shape; minimal adapter stub. |
| 0-2 | [Config schema for per-exchange limits](./0-2.md) | Done | YAML config: burst, steady rate, concurrency, header names, shared buckets. |
| 0-3 | [Header-aware rate limiter](./0-3.md) | Review | Token-bucket with adaptive rate; honors Retry-After & X-RateLimit-*; jittered backoff on 429/5xx. |
| 0-4 | [Stub server + tests](./0-4.md) | Proposed | Local HTTP server simulating 200/429/5xx and headers; unit/integration tests. |
| 0-5 | [Telemetry & runbook](./0-5.md) | Proposed | Structured logging; explain limiter behavior and troubleshooting. |
| 0-6 | [E2E CoS test for PBI-0](./0-6.md) | Proposed | End-to-end: burst then sustain, trigger 429, verify recovery & adaptation. |
