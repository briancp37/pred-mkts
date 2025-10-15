
#!/usr/bin/env bash
set -euo pipefail
OUT="context-pack-$(date +%Y%m%d-%H%M%S).md"
{
  echo "# Context Pack"
  echo "## Repo Tree (src/, docs/delivery/)"
  (echo '```'; command -v tree >/dev/null && tree -a -I '.git|__pycache__|.venv|artifacts' src docs/delivery || find src docs/delivery -maxdepth 3 -type f; echo '```')
  echo "## Registry"; echo '```yaml'; cat docs/delivery/registry.yml || true; echo '```'
  echo "## State"; echo '```md'; cat docs/delivery/_state.md || true; echo '```'
  echo "## Backlog"; echo '```md'; sed -n '1,200p' docs/delivery/backlog.md || true; echo '```'
  for d in docs/delivery/*/ ; do
    [ -d "$d" ] || continue
    echo "## $(basename "$d") PRD"; echo '```md'; sed -n '1,200p' "$d/prd.md" || true; echo '```'
    echo "## $(basename "$d") Tasks Index"; echo '```md'; sed -n '1,200p' "$d/tasks.md" || true; echo '```'
    for f in "$d"/*.md; do
      case "$f" in *tasks.md|*prd.md) continue;; esac
      echo "### Task File: $(basename "$f")"; echo '```md'; sed -n '1,200p' "$f" || true; echo '```'
    done
  done
  echo "## Recent Commits (last 30)"
  echo '```'; git --no-pager log --oneline -n 30 || true; echo '```'
} > "$OUT"
echo "Wrote $OUT"
