# Product Requirements Document (v0.1)
**Product:** Multi-Exchange Research & Data System  
**Owner:** Brian Pennington  
**Date:** 2025-10-15  
**Status:** Draft

---

## 1. Vision
Provide a unified data-storage and research platform that can ingest, normalize, and analyze prediction-market data from multiple exchanges (Polymarket, Kalshi, etc.), enabling systematic research and quantitative strategy development.

## 2. Goals
- Reliable, replayable ingestion of raw exchange data.
- Consistent normalization across heterogeneous APIs.
- Extensible interface for adding new exchanges.
- Rate-limit-aware, fault-tolerant fetching.
- Reproducible research environment with clear lineage from raw to normalized data.

## 3. Scope (Phase 1)
- Implement multi-exchange substrate (PBI-0).
- Fetch canonical Polymarket data (PBI-1).
- Normalize and version stored data (PBI-2).
- Provide basic CLI or API endpoints for research queries (future PBI).

## 4. Non-Goals (for now)
- Strategy execution or trading.
- Full visualization UI.
- Multi-tenant orchestration (later phases).

## 5. High-Level Architecture
- `src/core/` – shared substrate (`DataSource`, limiter, telemetry).  
- `src/exchanges/<name>/` – adapters per exchange.  
- `src/cli/` – command entrypoints (`fetch`, `backfill`, etc.).  
- `artifacts/raw/` – immutable JSON snapshots.  
- `artifacts/normalized/` – versioned Parquet tables.  

## 6. Dependencies
- Python 3.11+, `httpx` or `aiohttp` for HTTP.
- `pydantic` for configs/schemas.
- `uv` and `pre-commit` (already managed by template).

## 7. Open Questions
- Best persistence layer (S3, SQLite, DuckDB)?  
- Parallelization limits on Polymarket’s API?  
- Shared schema for multi-exchange price history?

---

_Last updated 2025-10-15_
