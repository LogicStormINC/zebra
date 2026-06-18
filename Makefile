PYTHON := uv run

.PHONY: sync check test tree

sync:
	uv sync --all-packages --group dev

check:
	uv run ruff check .
	uv run mypy packages apps

test:
	uv run pytest

tree:
	find apps packages tests -maxdepth 3 | sort
