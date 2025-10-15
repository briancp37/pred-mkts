
"""
Domain-neutral registry generator.
Writes docs/delivery/registry.yml as:
- code_paths: list of Python files under src/
- docs: important doc paths
Extend later if you want logical module names.
"""
from pathlib import Path
import yaml

src = Path("src")
code_paths = []
if src.exists():
    for p in src.rglob("*.py"):
        code_paths.append(str(p.as_posix()))
code_paths.sort()

reg = {
    "version": 1,
    "code_paths": code_paths,
    "configs": {},
    "constants": {},
    "docs": {
        "backlog": "docs/delivery/backlog.md",
        "product_prd": "docs/delivery/product-prd.md",
        "pbi_dirs_glob": "docs/delivery/*/",
    },
}

out = Path("docs/delivery/registry.yml")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(yaml.safe_dump(reg, sort_keys=False), encoding="utf-8")
print("registry.yml updated; files:", len(code_paths))
