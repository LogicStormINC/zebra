"""The worker package root must stay import-light (CA-HA-03 D1-v2).

The eager root previously pulled control/loop/main/recovery chains
(~1.5s in session children on the execution-only path).
"""

import subprocess
import sys

HEAVY_MODULES = (
    "zebra_agent_worker.control",
    "zebra_agent_worker.recovery",
    "zebra_agent_worker.main",
    "zebra_agent_worker.resume",
    "zebra_agent_worker.command_consumer",
)


def _run(code: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_root_import_does_not_load_service_chains():
    out = _run(
        "import sys, zebra_agent_worker;"
        "print(','.join(m for m in sys.modules if m.startswith('zebra_agent_worker.')))"
    )
    loaded = {m.strip() for m in out.split(",") if m.strip()}
    leaked = sorted(set(HEAVY_MODULES) & loaded)
    assert not leaked, f"eager import leaked service chains: {leaked}"


def test_exports_resolve_and_unknown_raises():
    out = _run(
        "import zebra_agent_worker, importlib\n"
        "for name in ('build_worker_loop_service', 'SessionExecutionService',"
        " 'CommandConsumption'):\n"
        "    value = getattr(zebra_agent_worker, name)\n"
        "    module = zebra_agent_worker._LAZY_EXPORTS[name]\n"
        "    assert getattr(importlib.import_module(module), name) is value\n"
        "try:\n"
        "    zebra_agent_worker.definitely_not_exported\n"
        "except AttributeError as error:\n"
        "    assert 'definitely_not_exported' in str(error)\n"
        "else:\n"
        "    raise AssertionError('unknown attribute must raise')\n"
        "print('ok')"
    )
    assert out.strip() == "ok"
