# PBI-1: Canonical Polymarket data fetch (raw)

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
- **Reuse PBI‑0 substrate**: `DataSource` adapter + header‑aware limiter + telemetry.
- **Adapter**: implement Polymarket in `src/pred_mkts/datasources/polymarket.py` (auth, `prepare_request`, `paginate`).
- **Snapshots**: JSONL pages at `artifacts/raw/polymarket/{YYYY‑MM‑DD}/{endpoint}/page-<n>.jsonl` plus `manifest.json` per run (start/end, endpoint, params, page count, commit SHA).
- **Resume**: store a `resume.json` marker with `last_updated_at` or equivalent so future runs can pick up from the last successful page/record.
- **CLI**: `pred-mkts fetch markets|outcomes|prices --updated-since=... [--output-dir ...] [--limit ...]`.
- **Runbook**: operator steps for first run, resume, backfill, and troubleshooting (link telemetry fields).

## UX/UI Considerations
- CLI only for this PBI; no UI planned.
- Makefile targets provide convenience wrappers for common fetches.

## Acceptance Criteria
- **Markets**: can fetch `updated_since=T` with safe pagination; retries/backoff on 429/5xx; raw pages + manifest written.
- **Outcomes/Contracts**: can fetch by market ids (batched if needed); same durability guarantees.
- **Prices/Quotes (phase 1)**: fetch available endpoint(s) over a bounded window; snapshot raw; document known gaps.
- **Resume**: a subsequent run continues from the last completed point without duplicating pages.
- **Telemetry**: decisions (ALLOW/THROTTLE/BACKOFF/ADAPTIVE) and headers observed are logged.
- **Runbook**: documents storage layout, first run, resume, backfill, and common errors.

## Dependencies
- PBI‑0 (substrate: datasource, limiter, telemetry) — must be `Done`.
- Polymarket API availability; OpenAPI/official docs.

## Open Questions
- Best mapping for `updated_since` semantics v. any `updated_after`/cursor/token provided by Polymarket.
- Price/quote history completeness and rate policy across endpoints.

## Related Tasks
See `./tasks.md`.
