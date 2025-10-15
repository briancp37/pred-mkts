#!/usr/bin/env bash
# scripts/bootstrap.sh
# Purpose: one-shot setup for this template in a fresh clone.
# - Ensures Python 3.11+ and uv are available
# - Creates a local venv and installs dev deps
# - Installs pre-commit hooks (including commit-msg prefix guard)
# - Initializes a git repo if needed and makes the first commit that satisfies the hook
#
# Usage:
#   bash scripts/bootstrap.sh
#   bash scripts/bootstrap.sh --project-name "My Project" --module mypkg --no-commit
#
# Notes:
# - This script is idempotent and safe to re-run.
# - It won’t push anything; it only operates locally.

set -euo pipefail

# ---------- defaults ----------
PROJECT_NAME=""
MODULE_NAME=""
DO_FIRST_COMMIT=1

# ---------- args ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-name) PROJECT_NAME="${2:-}"; shift 2 ;;
    --module)       MODULE_NAME="${2:-}"; shift 2 ;;
    --no-commit)    DO_FIRST_COMMIT=0; shift ;;
    -h|--help)
      cat <<'USAGE'
Usage: bash scripts/bootstrap.sh [--project-name "My Project"] [--module mypkg] [--no-commit]

Options:
  --project-name   Optional display name to record in pyproject/README title.
  --module         Optional python package name to set in pyproject (snake_case).
  --no-commit      Do not create the initial commit.
USAGE
      exit 0
    ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ---------- sanity checks ----------
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Please install Python 3.11+." >&2
  exit 1
fi

# (optional) check minor version >= 11
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJ=${PY_VER%%.*}; PY_MIN=${PY_VER#*.}
if [ "$PY_MAJ" -lt 3 ] || [ "$PY_MAJ" -eq 3 -a "$PY_MIN" -lt 11 ]; then
  echo "WARNING: Python $PY_VER detected; 3.11+ is recommended (AWS-friendly)." >&2
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Installing with pip (user)…"
  python3 -m pip install --user uv || pip3 install --user uv
  # ensure ~/.local/bin is on PATH for this shell
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv still not found on PATH. Add \$HOME/.local/bin to PATH and re-run." >&2
    exit 1
  fi
fi

# ---------- repo root check ----------
if [ ! -f "pyproject.toml" ] || [ ! -d ".git" ] && [ -d ".git" ]; then
  : # just a placeholder noop
fi

# ---------- optional project/module substitutions ----------
# Safe, best-effort replacements. They’ll only run if values are provided and patterns exist.
if [ -n "${PROJECT_NAME}" ]; then
  # Update README title if it starts with "# Cursor-First Project Template (Domain-Neutral)"
  if grep -q '^# Cursor-First Project Template (Domain-Neutral)$' README.md 2>/dev/null; then
    sed -i.bak "s/^# Cursor-First Project Template (Domain-Neutral)$/# ${PROJECT_NAME}/" README.md || true
    rm -f README.md.bak
  fi
  # Update pyproject description if desired (optional; adjust if you want)
  sed -i.bak "s/^description = \".*\"/description = \"${PROJECT_NAME}\"/" pyproject.toml 2>/dev/null || true
  rm -f pyproject.toml.bak 2>/dev/null || true
fi

if [ -n "${MODULE_NAME}" ]; then
  # Update the project name if desired (this template is domain-neutral)
  sed -i.bak "s/^name = \"project_template\"/name = \"${MODULE_NAME}\"/" pyproject.toml 2>/dev/null || true
  rm -f pyproject.toml.bak 2>/dev/null || true
fi

# ---------- uv env + dev deps ----------
echo "Setting up uv environment…"
uv venv
uv pip install --upgrade pip
uv add --dev pre-commit pyyaml

# ---------- pre-commit hooks ----------
echo "Installing pre-commit hooks…"
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

# ---------- initialize git if needed ----------
if [ ! -d ".git" ]; then
  echo "Initializing git repository…"
  git init -b main
fi

# ---------- first commit (satisfies <pbi>-<task> rule) ----------
if [ "$DO_FIRST_COMMIT" -eq 1 ]; then
  git add .
  # If repo is already committed, this will no-op or create a new commit
  set +e
  git commit -m "1-0 bootstrap repo skeleton"
  COMMIT_RC=$?
  set -e
  if [ $COMMIT_RC -ne 0 ]; then
    echo "Note: initial commit was not created (possibly nothing new to commit)."
  fi
fi

cat <<'DONE'

✅ Bootstrap complete.

Next steps:
1) Open docs/delivery/product-prd.md and write your short Product PRD v0.1.
2) Add initial PBIs to docs/delivery/backlog.md (status: Proposed).
3) Flesh out PBI-1 in docs/delivery/1/prd.md and docs/delivery/1/tasks.md.
4) Set current focus once in tools/update_state.py:
   ACTIVE_PBI = "1"
   ACTIVE_TASKS = ["1-1"]  # example
   touchpoints = ["src/path/you'll/work/on.py"]
5) Commit normally with a task prefix (hook enforced), e.g.:
   git add .
   git commit -m "1-1 scaffold project config"
6) When you want ChatGPT to help draft new PBIs/tasks:
   bash scripts/context-pack.sh
   (paste the generated markdown into the chat)

Tip: If you haven't added a remote yet, do:
  git remote add origin <your GitHub repo URL>
  git push -u origin main

DONE
