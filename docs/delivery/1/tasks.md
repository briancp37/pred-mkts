# Tasks for PBI 1: Canonical Polymarket data fetch (raw)
This document lists all tasks associated with PBI 1.

**Parent PBI**: [PBI 1: Canonical Polymarket data fetch (raw)](./prd.md)

## Task Summary
| Task ID | Name | Status | Description |
| :------ | :--- | :----- | :---------- |
| 1-1 | [Finalize PBI-1 PRD](./1-1.md) | Review | Flesh out `docs/delivery/1/prd.md` to Agreed: scope, endpoints, storage layout, CoS. |
| 1-2 | [Polymarket API surface guide](./1-2.md) | Proposed | Create `1-2-polymarket-guide.md` from OpenAPI/web docs; pagination, filters, limits. |
| 1-3 | [Polymarket DataSource adapter](./1-3.md) | Proposed | Implement `datasources/polymarket.py` using PBI-0 interfaces; auth, prepare_request, paginate. |
| 1-4 | [Raw snapshot writer + layout](./1-4.md) | Proposed | Define snapshot directory scheme, metadata manifest, atomic writes. |
| 1-5 | [Markets fetch: updated_since → raw](./1-5.md) | Proposed | Pull markets incrementally with resume marker; write raw pages + manifest. |
| 1-6 | [Contracts/outcomes fetch](./1-6.md) | Proposed | Fetch outcomes/contracts linked to markets; same robustness and snapshotting. |
| 1-7 | [Prices/quotes (phase 1)](./1-7.md) | Proposed | Fetch available price/quote or trades endpoint; document gaps; snapshot raw. |
| 1-8 | [CLI commands & Make targets](./1-8.md) | Proposed | `pred-mkts fetch markets|outcomes|prices --updated-since=...`; add Make shortcuts. |
| 1-9 | [Runbook for PBI-1 ops](./1-9.md) | Proposed | Operator guide: first run, resume, backfill, troubleshooting. |
| 1-10 | [E2E CoS test for PBI-1](./1-10.md) | Proposed | End-to-end test (stub/fixtures) verifying CoS across 1-3→1-8. |
