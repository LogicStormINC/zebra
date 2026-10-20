#!/usr/bin/env bash
# User-operated activation; stop before replacing services if isolation is unavailable.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
env_file=${1:?usage: recreate-application.sh ENV_FILE [--trench-compat]}
compose=(docker compose --env-file "$env_file"
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml)
if [[ ${2:-} == --trench-compat ]]; then
  compose+=(-f docker/compose.trench-compat.yml)
elif [[ -n ${2:-} ]]; then
  echo "unknown option: $2" >&2
  exit 2
fi
"${compose[@]}" run --rm --no-deps --entrypoint /app/.venv/bin/python \
  zebra-worker -m zebra_agent_worker.runtime_preflight
"${compose[@]}" up -d --no-build --no-deps --force-recreate --wait zebra-api zebra-worker
