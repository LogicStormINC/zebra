from dataclasses import replace
from subprocess import CompletedProcess, TimeoutExpired

import pytest
from agent_core.ports.runtime import RuntimeCapabilityError
from zebra_agent_config import RuntimeSettings, load_settings
from zebra_agent_worker import runtime_preflight


@pytest.mark.parametrize("runtimes,available", [('{}', False), ('{"runsc":{}}', True)])
def test_worker_health_probes_required_handler_without_creating_a_container(
    monkeypatch, runtimes, available,
):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return CompletedProcess(command, 0, "26.1\n" + runtimes, "")

    monkeypatch.setattr(runtime_preflight, "pin_cloud_engine", lambda _: runner)
    settings = replace(load_settings(env={}), runtime=RuntimeSettings(
        runtime_class="gvisor", image="python@sha256:" + "a" * 64,
    ))
    if available:
        runtime_preflight.check_runtime(settings)
    else:
        with pytest.raises(RuntimeCapabilityError, match="does not advertise runtime runsc"):
            runtime_preflight.check_runtime(settings)
    assert len(calls) == 1
    assert calls[0][1] == "info"


@pytest.mark.parametrize("error", [RuntimeCapabilityError("missing runsc"),
                                  TimeoutExpired("engine", 10)])
def test_preflight_reports_unavailable_without_false_readiness(monkeypatch, capsys, error):
    def unavailable(_):
        raise error

    monkeypatch.setattr(runtime_preflight, "check_runtime", unavailable)
    assert runtime_preflight.main() == 1
    output = capsys.readouterr().out
    assert '"status": "unavailable"' in output
    assert '"code": "runtime_unavailable"' in output
