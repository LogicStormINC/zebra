"""python3 tests/test_command_refusal_binding.py; actual deferred callback, no IO."""

import ast
from pathlib import Path
from types import SimpleNamespace

source = (
    Path(__file__).resolve().parents[1]
    / "cloud-patches/overrides/apps/worker/src/zebra_agent_worker/command_consumer.py"
)
callback = next(
    node
    for node in ast.walk(ast.parse(source.read_text()))
    if isinstance(node, ast.FunctionDef) and node.name == "refuse"
)
original_database = SimpleNamespace(_dsn="original-database", deployment_namespace="original-scope")
original_event = object()
recorded = []


def persist(*args, **kwargs):
    recorded.append((args, kwargs))
    return "original-receipt"


scope = dict(
    database=original_database,
    command_event=original_event,
    persist_fresh_disposition=persist,
)
exec(compile(ast.Module(body=[callback], type_ignores=[]), str(source), "exec"), scope)
# A later scanner iteration must not redirect a previously handed-off refusal.
scope["database"] = SimpleNamespace(_dsn="later-database", deployment_namespace="later-scope")
scope["command_event"] = object()
lease = object()
assert (
    scope["refuse"](lease, SimpleNamespace(code="expired", reason="refused")) == "original-receipt"
)
assert recorded == [
    (
        ("original-database", "original-scope", lease),
        dict(code="expired", reason="refused", accepted_event=original_event),
    )
]
print("PASS deferred refusal persists only the original command, database and scope")
