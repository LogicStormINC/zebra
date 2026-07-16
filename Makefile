PYTHON := uv run

.PHONY: sync check eval test tree api-serve ui-build ui-dev ui-tauri-build ui-tauri-check

sync:
	uv sync --all-packages --group dev

check:
	uv run python scripts/check_file_sizes.py
	uv run ruff check .
	uv run mypy packages apps
	uv run python scripts/eval_release_check.py

eval:
	uv run python scripts/eval_release_check.py

test:
	uv run pytest

tree:
	find apps packages tests -maxdepth 3 | sort

api-serve:
	uv run uvicorn zebra_agent_api.http:create_http_app --factory --host 127.0.0.1 --port 8000

ui-build:
	cd UI/desktop && CI=true pnpm install --ignore-scripts && pnpm build

ui-dev:
	cd UI/desktop && CI=true pnpm install --ignore-scripts && pnpm dev

ui-tauri-build:
	cd UI/desktop && CI=true pnpm install --ignore-scripts && pnpm tauri:build

ui-tauri-check:
	cd UI/desktop && CI=true pnpm install --ignore-scripts && pnpm tauri:check
