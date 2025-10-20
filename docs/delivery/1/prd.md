# PBI-1: Canonical Polymarket data fetch (raw)

[View in Backlog](../backlog.md) | [View Tasks](./tasks.md)

## Overview
Fetch and store **raw Polymarket data** (markets, outcomes/contracts, and prices/quotes if available) using the PBI‑0 substrate (DataSource + header‑aware rate limiter + telemetry). Produce timestamped, reproducible snapshots suitable for later normalization (PBI‑2).

## Problem Statement
Polymarket exposes thousands of markets with frequent updates. We need a reliable, resumable fetch that respects rate limits, paginates safely, and records exactly‑what‑we‑saw snapshots with run metadata for auditability and research reproducibility.

## User Stories
- As a researcher, I can fetch **all markets updated since T** and store raw responses with manifests.
- As a researcher, I can **fetch outcomes/contracts** for a set of market ids with the same robustness and layout.
- As a researcher, I can fetch **prices/quotes/trades (phase 1)** over a time window and save raw results even if history is incomplete.
- As an operator, I have a **CLI** and **runbook** to run, resume, and backfill safely.

## Technical Approach

### PBI-0 Substrate Integration
This PBI builds on **[PBI-0: Multi-exchange substrate](../0/prd.md)** which provides:
- `DataSource` interface with `prepare_request()` and `paginate()` methods
- Header-aware rate limiter with adaptive token buckets
- Telemetry for request tracking and decision logging

### API Endpoints
Polymarket API base URL: `https://api.polymarket.com`

| Endpoint | Path | Purpose | Key Parameters |
|----------|------|---------|----------------|
| **Markets** | `/markets` | List all markets with metadata | `updated_since` (ISO8601), `limit`, `offset` or cursor |
| **Outcomes** | `/markets/{market_id}/outcomes` or `/outcomes` | Get outcomes/contracts for markets | `market_ids[]`, `limit`, `offset` |
| **Prices/Quotes** | `/prices` or `/trades` | Historical price/trade data | `market_id`, `outcome_id`, `start_time`, `end_time`, `limit` |

_Note: Exact paths will be verified in Task 1-2 (API surface guide) using official Polymarket documentation._

### Snapshot Storage Layout
Raw fetched data is stored in timestamped directories:

```
artifacts/
  raw/
    polymarket/
      {YYYY-MM-DD}/              # Fetch date (local timezone)
        markets/
          page-0001.jsonl        # Raw JSON response per page
          page-0002.jsonl
          ...
          manifest.json          # Run metadata (see below)
          resume.json            # Resume marker for incremental fetches
        outcomes/
          page-0001.jsonl
          manifest.json
          resume.json
        prices/
          page-0001.jsonl
          manifest.json
          resume.json
```

### Manifest Schema
Each endpoint run produces a `manifest.json` with the following fields:

```json
{
  "run_id": "uuid-v4",
  "endpoint": "markets|outcomes|prices",
  "exchange": "polymarket",
  "start_time": "ISO8601 timestamp",
  "end_time": "ISO8601 timestamp",
  "status": "success|partial|failed",
  "params": {
    "updated_since": "ISO8601 or null",
    "limit": 100,
    "...": "other query params"
  },
  "page_count": 42,
  "record_count": 4197,
  "commit_sha": "git commit hash at run time",
  "telemetry_summary": {
    "requests_made": 42,
    "throttles": 3,
    "backoffs": 0,
    "errors": []
  }
}
```

### Resume Marker Semantics
Each endpoint maintains a `resume.json` file:

```json
{
  "last_completed_page": 42,
  "last_updated_at": "ISO8601 timestamp of most recent record",
  "last_record_id": "optional identifier for cursor-based pagination",
  "run_id": "uuid-v4 of run that created this marker"
}
```

On subsequent runs:
1. If `resume.json` exists, fetch only records `updated_since` the marker's timestamp
2. If pagination is cursor-based, use `last_record_id` as the starting cursor
3. If fetch completes successfully, update `resume.json` with new values
4. If fetch fails mid-run, `resume.json` reflects the last **successfully written** page

### Implementation Components
- **Adapter**: implement Polymarket in `src/pred_mkts/datasources/polymarket.py` (auth, `prepare_request`, `paginate`)
- **Snapshot writer**: atomic writes with temp files, manifest generation (Task 1-4)
- **CLI**: `pred-mkts fetch markets|outcomes|prices --updated-since=... [--output-dir ...] [--limit ...]`
- **Runbook**: operator steps for first run, resume, backfill, and troubleshooting (link telemetry fields)

## UX/UI Considerations
- CLI only for this PBI; no UI planned.
- Makefile targets provide convenience wrappers for common fetches.

## Acceptance Criteria / Conditions of Satisfaction

### Markets Endpoint
- Can fetch markets with `updated_since=<ISO8601>` parameter for incremental updates
- Safe pagination with cursor or offset-based strategy (per API design)
- Retries with jittered exponential backoff on 429/5xx responses
- Raw response pages written as `page-NNNN.jsonl` files
- `manifest.json` generated with all required fields (run metadata, params, counts, commit SHA)
- `resume.json` marker updated after each successful page write

### Outcomes/Contracts Endpoint
- Can fetch outcomes/contracts for a list of market IDs
- Batched requests if API limits single-market queries
- Same durability guarantees as markets (atomic writes, manifest, resume marker)
- Raw responses stored in `artifacts/raw/polymarket/{date}/outcomes/`

### Prices/Quotes Endpoint (Phase 1)
- Can fetch available price/quote or trade history endpoint(s) for a time window
- Raw data snapshotted even if historical data has known gaps
- Documentation of API limitations and known gaps in runbook
- Same storage and resume semantics as other endpoints

### Resume & Incremental Fetch
- Subsequent runs read `resume.json` and fetch only new/updated records since last run
- No duplicate pages written (idempotent behavior)
- If a run fails mid-flight, `resume.json` reflects last successfully written page
- Resume works correctly across different date directories

### Telemetry & Observability
- All rate limiter decisions logged (ALLOW/THROTTLE/BACKOFF/ADAPTIVE) using PBI-0 telemetry
- HTTP headers observed (`Retry-After`, `X-RateLimit-*`) logged per request
- Manifest includes telemetry summary (request count, throttle count, errors)

### Operational Runbook
- Documents snapshot storage layout with examples
- Provides commands for first run, resume, and backfill scenarios
- Links to telemetry fields from PBI-0 for troubleshooting
- Describes common errors (429, 5xx, no progress) and resolution steps

### CLI Interface
- Command: `pred-mkts fetch <markets|outcomes|prices> --updated-since=<ISO8601> [--output-dir=...] [--limit=...]`
- Returns exit code 0 on success, non-zero on failure
- Displays progress information (pages fetched, records processed)
- Makefile targets wrap common fetch patterns for convenience

## Dependencies
- **[PBI-0: Multi-exchange substrate + precise rate limiting](../0/prd.md)** — must be `Done`
  - Provides `DataSource` interface
  - Provides header-aware rate limiter with adaptive token buckets
  - Provides telemetry infrastructure for request tracking
- **Polymarket API** availability and documentation
  - OpenAPI specification or official API docs
  - Verification of endpoint paths and parameters (covered in Task 1-2)

## Open Questions
- Best mapping for `updated_since` semantics v. any `updated_after`/cursor/token provided by Polymarket.
- Price/quote history completeness and rate policy across endpoints.

## Related Tasks
See `./tasks.md`.
