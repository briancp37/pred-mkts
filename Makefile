
.PHONY: setup hooks test context-pack

bootstrap:
	bash scripts/bootstrap.sh $(ARGS)

setup:
	uv venv
	uv pip install --upgrade pip
	uv add --dev pre-commit pyyaml
	uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

hooks:
	uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

test:
	uv run pytest -q

context-pack:
	bash scripts/context-pack.sh

help:
	@echo "Available commands:"
	@echo "  make bootstrap ARGS='--project-name \"My Project\" --module mypkg'  Setup project"
	@echo "  make setup         Setup uv env manually"
	@echo "  make hooks         Reinstall git hooks"
	@echo "  make test          Run pytest"
	@echo "  make context-pack  Generate context pack snapshot"