#!/usr/bin/env bash
# User-operated activation; stop before replacing services if isolation is unavailable.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
compose=(docker compose --env-file docker/trench-acceptance.env
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml)
"${compose[@]}" run --rm --no-deps --entrypoint /app/.venv/bin/python \
  zebra-worker -m zebra_agent_worker.runtime_preflight
"${compose[@]}" up -d --no-build --no-deps --force-recreate --wait zebra-api zebra-worker
