
import sys, re, pathlib
msg = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
if not re.match(r"^[0-9]+-[0-9]+\s", msg):
    sys.stderr.write("Commit message must start with '<pbi>-<task> ', e.g., '1-2 implement feature'\n")
    sys.exit(1)
