# Cursor-First Project Template (Domain-Neutral)

This repository provides a **Cursor-optimized software development template** — complete with rules, automation, and folder structure that allow humans and AI agents to work together consistently and safely.

It encodes all of the following:
- 🧭 **Process governance** — PBIs, tasks, PRDs, and state tracking.
- ⚙️ **Automation** — pre-commit hooks for registry/state synchronization.
- 🧩 **Extensibility** — portable structure usable for any domain.
- 🤖 **Agent-readable context** — so tools like Cursor or ChatGPT can reconstruct your active state automatically.

---

## 🧱 Repository Overview

| Folder / File | Purpose |
|----------------|----------|
| `docs/delivery/` | Source-of-truth for backlog, PBIs, tasks, PRDs, registry, and state. |
| `tools/` | Internal automation scripts for state & registry sync, commit-message checks. |
| `scripts/` | Utility scripts for developers (bootstrap setup, context pack). |
| `.github/` | PR template and status-sync workflow. |
| `.pre-commit-config.yaml` | Hook definitions for commit guardrails. |
| `Makefile` | Primary command surface for developers. |
| `rules.md` | Full project governance and operating policy. |
| `src/` | Your actual application code (empty by default). |

---

## 🚀 One-Shot Bootstrap

Run this once in a **fresh clone** to set up your environment, pre-commit hooks, and the first valid commit:

```bash
make bootstrap ARGS='--project-name "My Project" --module mypkg'
```

If you prefer to invoke the script directly:

```bash
bash scripts/bootstrap.sh --project-name "My Project" --module mypkg
```

### Options
- `--project-name "My Project"` — updates the display name in README and `pyproject.toml`
- `--module mypkg` — sets the Python package name in `pyproject.toml`
- `--no-commit` — skips creating the initial `1-0 bootstrap repo skeleton` commit

After running bootstrap:
1. Fill in `docs/delivery/product-prd.md` and `docs/delivery/backlog.md`.
2. Flesh out **PBI-1** in `docs/delivery/1/prd.md` and `docs/delivery/1/tasks.md`.
3. Set the current PBI and task once in `tools/update_state.py`.
4. Commit using the required prefix, e.g.:
   ```bash
   git commit -m "1-1 add task sync logic"
   ```
5. When you want ChatGPT/Cursor to generate new PBIs or tasks, run:
   ```bash
   make context-pack
   ```
   and paste the resulting markdown into ChatGPT.

---

## ⚙️ What’s Automated vs Manual

### Automated (via pre-commit)
- **Commit messages** must start with `<pbi>-<task>` (e.g., `1-2`).
- **Registry** (`docs/delivery/registry.yml`) updates automatically when you change code paths.
- **State file** (`docs/delivery/_state.md`) updates automatically when you switch tasks.

### Manual (developer actions)
- Edit `tools/update_state.py` when switching PBIs or tasks:
  ```python
  ACTIVE_PBI = "1"
  ACTIVE_TASKS = ["1-1"]
  touchpoints = ["src/path/to/file.py"]
  ```
- Keep your PBI’s `tasks.md` index and individual task files aligned.
- Approve, reject, or close tasks according to your `rules.md` workflow.

---

## 🧰 Common Make Targets

| Command | Purpose |
|----------|----------|
| `make bootstrap ARGS='--project-name "My Project" --module mypkg'` | Full environment setup (runs `scripts/bootstrap.sh`). |
| `make setup` | Rebuild `.venv` and reinstall dev deps manually. |
| `make hooks` | Re-install pre-commit hooks if missing. |
| `make test` | Run pytest inside uv virtualenv. |
| `make context-pack` | Export a markdown snapshot of repo state for AI agents. |

---

## 🧩 Integration With Cursor

Cursor automatically reads:
- `rules.md` for agent policy and development rules.
- `docs/delivery/` to reconstruct your backlog, PRDs, and active tasks.

When you open this project in Cursor, agents will:
- Adhere to the rule set.
- Limit actions to approved files/paths.
- Update `_state.md` and `registry.yml` automatically through hooks.

---

## 📖 Policy Files

The complete process policy lives in **`rules.md`**, which defines:
- Architectural compliance rules
- Change management flow
- PBI and task status transitions
- Testing strategy
- Repository context artifact rules  
  (registry, state index, grep anchors, commit conventions, status sync CI)

If you change the structure or add new automation, update both:
- `rules.md`
- `docs/delivery/registry.yml`

---

## 🧪 Testing

Testing follows the conventions in your `rules.md` section 5:
- Unit tests → `tests/unit/`
- Integration tests → `tests/integration/`
- E2E tests → `tests/e2e/`

Run tests via:
```bash
make test
```

---

## 🧭 Typical Developer Flow

1. `make bootstrap ARGS='--project-name "My Project" --module mypkg'`  
2. Write or update PBIs in `docs/delivery/backlog.md`  
3. Create tasks under `docs/delivery/<PBI>/tasks.md`  
4. Set active task in `tools/update_state.py`  
5. Code, commit with `<pbi>-<task>` prefix  
6. `make context-pack` for review or handoff  

---

## 🧑‍💻 Rationale

**Python 3.11**  
→ Matches AWS Lambda/Glue environments for maximum portability.

**uv**  
→ Fast, deterministic package manager that isolates envs cleanly.  

**pre-commit**  
→ Ensures every commit maintains consistency (hooks + validation).  

**Cursor compliance rules**  
→ Guarantees both human and AI agents follow the same structured workflow with full auditability.

---

## 🏁 Next Steps

1. Create your own GitHub repo from this template.  
2. Clone it and run `make bootstrap ARGS='--project-name "My Project" --module mypkg'`.  
3. Commit your first real PBI and task.  
4. Start coding — your process governance and automation are already in place.

---

**Happy building — your agents now have a safe, automated workspace.**
