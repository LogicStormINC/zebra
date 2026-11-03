"""Dependency diagnostics are bounded and cannot turn refusal into permission."""

import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionError
from zebra_agent_worker.host_authority_probe import (
    HostAuthorityProbe,
    HostAuthorityUnavailable,
)


@pytest.mark.parametrize(
    ("status", "reason", "error"),
    [
        (503, "http_error", HostAuthorityUnavailable),
        (403, "http_denied", ExecutionAuthorityResolutionError),
        (None, "timeout", HostAuthorityUnavailable),
        (None, "invalid_response", HostAuthorityUnavailable),
    ],
)
def test_probe_failure_reports_only_safe_transport_facts(caplog, status, reason, error):
    probe = object.__new__(HostAuthorityProbe)
    request_id = str(uuid4())
    result = SimpleNamespace(metadata={
        "http_status": status,
        "reason": "timeout" if reason == "timeout" else "invalid_body",
        "request_id": request_id,
        "detail": "private-response",
    })
    with caplog.at_level(logging.WARNING), pytest.raises(error) as failure:
        probe._refuse(result, started=0)
    assert isinstance(failure.value, HostAuthorityUnavailable) == (status != 403)
    assert f"reason={reason}" in caplog.text
    assert f"http_status={status}" in caplog.text
    assert request_id in caplog.text
    assert "private-response" not in caplog.text
