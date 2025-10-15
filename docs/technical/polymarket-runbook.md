# Polymarket Runbook (PBI‑1)

## First Run
1. Ensure PBI‑0 substrate is installed and configured (limits.yml).
2. Set environment (API base URL, token if required).
3. Run markets fetch with an `--updated-since` anchor (e.g., 7 days back).
4. Verify `artifacts/raw/polymarket/...` tree and `manifest.json`.

## Resume & Backfill
- Resume uses `resume.json` marker per endpoint; safe to re-run.
- Backfill: run multiple windows sequentially; manifests record params.

## Troubleshooting
- **429**: limiter honors `Retry‑After`; check telemetry for THROTTLE/BACKOFF.
- **5xx**: bounded retries; inspect logs.
- **No progress**: verify pagination params and stop condition in guide.

## Telemetry Keys (from PBI‑0)
- decision, sleep_s, elapsed_ms, headers_seen, status, endpoint, exchange.

## Expected Layout
```
artifacts/
  raw/
    polymarket/
      YYYY-MM-DD/
        markets/
          page-0001.jsonl
          page-0002.jsonl
          manifest.json
        outcomes/
          ...
        prices/
          ...
```
