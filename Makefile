PYTHON := uv run

.PHONY: sync check eval test tree

sync:
	uv sync --all-packages --group dev

check:
	uv run ruff check .
	uv run mypy packages apps
	uv run python scripts/eval_release_check.py

eval:
	uv run python scripts/eval_release_check.py

test:
	uv run pytest

tree:
	find apps packages tests -maxdepth 3 | sort
