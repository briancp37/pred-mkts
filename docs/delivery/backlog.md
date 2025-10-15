# Backlog

| ID | Actor | User Story | Status | Conditions of Satisfaction (CoS) |
| :-- | :---- | :--------- | :----- | :------------------------------- |
| 0 | Developer | As a developer, I have a reusable multi-exchange fetch substrate with a header-aware rate limiter, so I can add Polymarket now and Kalshi later without refactoring. | Proposed | Common `DataSource` interface; per-exchange config; header-aware limiter (429/Retry-After/RL headers); per-host token buckets; basic telemetry. |
| 1 | Researcher | As a researcher, I can pull canonical Polymarket market & outcome data into raw, timestamped storage so I can analyze it reproducibly. | Proposed | Incremental fetch by updated_since; uses substrate from PBI-0; writes raw snapshots; runbook. |
| 2 | Researcher | As a researcher, I can query normalized, versioned tables so I can run strategies over time. | Proposed | Documented schema; idempotent normalizer; backfill job; basic DQ checks. |
