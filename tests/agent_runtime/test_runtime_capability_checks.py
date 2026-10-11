from subprocess import TimeoutExpired
from unittest.mock import Mock

import pytest
from agent_core.ports.runtime import (
    RuntimeCapabilities,
    RuntimeCapabilityError,
    RuntimeClass,
    RuntimePort,
)
from agent_runtime.capability_checks import require_runtime_capabilities


def capabilities(*, available=False, retryable=False):
    return RuntimeCapabilities(
        RuntimeClass.GVISOR, available, "docker", reason="missing runtime", retryable=retryable,
    )


@pytest.mark.parametrize("failure", [capabilities(retryable=True), TimeoutExpired("docker", 2)])
def test_preflight_recovers_transient_reads_without_provisioning(monkeypatch, failure):
    monkeypatch.setattr("agent_runtime.capability_checks.sleep", lambda _: None)
    runtime = Mock(spec=RuntimePort)
    runtime.inspect_capabilities.side_effect = [failure, capabilities(available=True)]
    assert require_runtime_capabilities(runtime).available
    assert runtime.inspect_capabilities.call_count == 2
    runtime.provision.assert_not_called()


@pytest.mark.parametrize("failure", [capabilities(retryable=True), TimeoutExpired("docker", 2)])
def test_preflight_has_a_three_probe_bound(monkeypatch, failure):
    monkeypatch.setattr("agent_runtime.capability_checks.sleep", lambda _: None)
    runtime = Mock(spec=RuntimePort)
    runtime.inspect_capabilities.side_effect = [failure] * 3
    with pytest.raises(RuntimeCapabilityError):
        require_runtime_capabilities(runtime)
    assert runtime.inspect_capabilities.call_count == 3
    runtime.provision.assert_not_called()


def test_missing_isolation_fails_immediately_without_fallback():
    runtime = Mock(spec=RuntimePort)
    runtime.inspect_capabilities.return_value = capabilities()
    with pytest.raises(RuntimeCapabilityError, match="missing runtime"):
        require_runtime_capabilities(runtime)
    assert runtime.inspect_capabilities.call_count == 1
    runtime.provision.assert_not_called()
