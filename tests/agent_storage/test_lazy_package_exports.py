"""The package root must stay import-light; re-exports resolve lazily.

2026-11-09 CA-HA-03 D1 regression: the eager root pulled ~35 submodules
(~2s in worker session children, 67% of the measured 3.0 CPU.s boot cost).
"""

import subprocess
import sys

HEAVY_MODULES = (
    # The postgres subpackage root itself is now lazy-cheap; its adapters
    # and every other heavyweight module must stay unloaded.
    "agent_storage.postgres_composition",
    "agent_storage.postgres.agent_registry",
    "agent_storage.postgres.agent_tasks",
    "agent_storage.postgres.leases",
    "agent_storage.artifact_objects",
    "agent_storage.memories",
    "agent_storage.projections",
    "agent_storage.workspaces",
)


def _run(code: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_root_import_does_not_load_heavy_submodules():
    out = _run(
        "import sys, agent_storage, agent_storage.postgres as pg;"
        "assert pg.__doc__; "
        "print(','.join(m for m in sys.modules if m.startswith('agent_storage.')))"
    )
    loaded = {m.strip() for m in out.split(",") if m.strip()}
    leaked = sorted(set(HEAVY_MODULES) & loaded)
    assert not leaked, f"eager import leaked heavy submodules: {leaked}"


def test_all_exports_resolve_to_source_attributes():
    out = _run(
        "import agent_storage, importlib, json\n"
        "missing, mismatched = [], []\n"
        "for name in agent_storage.__all__:\n"
        "    try:\n"
        "        value = getattr(agent_storage, name)\n"
        "    except AttributeError:\n"
        "        missing.append(name); continue\n"
        "    module = agent_storage._LAZY_EXPORTS.get(name)\n"
        "    if module is not None and getattr(importlib.import_module(module), name) is not value:\n"
        "        mismatched.append(name)\n"
        "print(json.dumps({'missing': missing, 'mismatched': mismatched}))"
    )
    report = eval(out)
    assert not report["missing"], f"unresolvable exports: {report['missing']}"
    assert not report["mismatched"], f"identity mismatches: {report['mismatched']}"


def test_dir_and_unknown_attribute_contract():
    out = _run(
        "import agent_storage\n"
        "names = dir(agent_storage)\n"
        "assert 'SQLiteAgentTaskStore' in names and 'PostgresEventStore' in names\n"
        "try:\n"
        "    agent_storage.definitely_not_exported\n"
        "except AttributeError as error:\n"
        "    assert 'definitely_not_exported' in str(error)\n"
        "else:\n"
        "    raise AssertionError('unknown attribute must raise')\n"
        "print('ok')"
    )
    assert out.strip() == "ok"
