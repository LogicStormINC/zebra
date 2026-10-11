"""Gateway cleanup is one-shot even when finalization encounters a second fault."""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

from zebra_agent_worker.gateway_release import GatewayRelease


def test_gateway_cleanup_runs_once_after_reply():
    gateway, recorder = Mock(), Mock()
    release = GatewayRelease(gateway, recorder, started_at=datetime.now(UTC))
    assert release() is None
    assert release() is None
    gateway.close.assert_called_once_with()


def test_cleanup_failure_has_one_durable_receipt_without_repeated_close():
    error = RuntimeError("socket teardown failed")
    gateway, recorder = Mock(), Mock()
    gateway.close.side_effect = error
    release = GatewayRelease(gateway, recorder, started_at=datetime.now(UTC))
    with patch("zebra_agent_worker.gateway_release.persist_runtime_cleanup_failure") as persist:
        assert release() is error
        assert release() is None
    gateway.close.assert_called_once_with()
    persist.assert_called_once()
    assert persist.call_args.kwargs["target"] == "tool_gateway"
    assert persist.call_args.kwargs["recorder"] is recorder


def test_evidence_failure_retains_original_cleanup_error():
    error = RuntimeError("socket teardown failed")
    gateway = Mock()
    gateway.close.side_effect = error
    release = GatewayRelease(gateway, Mock(), started_at=datetime.now(UTC))
    with patch(
        "zebra_agent_worker.gateway_release.persist_runtime_cleanup_failure",
        side_effect=ValueError("lease superseded"),
    ):
        assert release() is error
    assert any("ValueError" in note for note in error.__notes__)
    assert release() is None
    gateway.close.assert_called_once_with()
