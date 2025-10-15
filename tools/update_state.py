
"""
Set ACTIVE_PBI / ACTIVE_TASKS below when you switch tasks.
This script renders docs/delivery/_state.md automatically via pre-commit.
"""
from pathlib import Path

# ---- EDIT THESE WHEN YOU SWITCH TASKS ----
ACTIVE_PBI = "0"          # e.g., "1"
ACTIVE_TASKS = ["0-5"]        # e.g., ["1-2"]
touchpoints = ["config/limits.yml", "src/pred_mkts/core/config.py", "tests/unit/test_config.py"]         # e.g., ["src/app/config.py"]
# ------------------------------------------

content = f"""# Project State (manual, short)
- **Active PBI**: {("(none)" if not ACTIVE_PBI else f"PBI-{ACTIVE_PBI} (docs/delivery/{ACTIVE_PBI}/prd.md)")}
- **Active Task(s)**: {("(none)" if not ACTIVE_TASKS else ", ".join(ACTIVE_TASKS))}
- **Code Touchpoints**: {("(none)" if not touchpoints else ", ".join(touchpoints))}
"""
Path("docs/delivery/_state.md").write_text(content, encoding="utf-8")
print("_state.md updated")
