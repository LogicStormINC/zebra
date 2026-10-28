#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
ZPY=${ZEBRA_PYTHON:-$ROOT/.venv/bin/python}
# Force this checkout's sources even when a supplied Python has other editable installs.
for SOURCE in "$ROOT"/packages/*/src "$ROOT"/apps/*/src; do
  export PYTHONPATH="$SOURCE${PYTHONPATH:+:$PYTHONPATH}"
done
"$ZPY" "$ROOT/tests/conformance/agui_contract/selfcheck.py"
"$ZPY" -m unittest discover -s "$ROOT/tests/conformance/agui_contract" -p 'test_*.py' -v
