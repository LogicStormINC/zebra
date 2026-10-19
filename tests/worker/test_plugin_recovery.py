"""Recovery trusts admitted origins only and never resolves a replacement installation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.domain.extension_snapshots import ExtensionSnapshot, McpSnapshotEntry
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_core.domain.plugin_snapshots import PluginSnapshot
from zebra_agent_worker.extension_recovery import RecoveredTurnExtension
from zebra_agent_worker.worker_plugins import WorkerPluginSource, prepare_worker_plugins

from tests.agent_storage.test_postgres_plugin_installations import SCOPE, _record


def _source(*, direct=False):
    record = _record(enabled=True)
    snapshot = ExtensionSnapshot(
        scope=SCOPE,
        session_id="session-a",
        turn_id="turn-a",
        mcp=(
            McpSnapshotEntry(
                connection=record.bindings[0].connection,
                catalog_digest=record.bindings[0].catalog_digest,
            ),
        ),
        plugins=(PluginSnapshot.from_installation(record),),
        direct_mcp=(record.bindings[0].connection.connection_id,) if direct else (),
    )
    extension = RecoveredTurnExtension(SCOPE, snapshot, SimpleNamespace())
    installations, packages = AsyncMock(), AsyncMock()
    installations.get_current_batch.return_value = (record,)
    installations.get_revision.return_value = record
    return extension, WorkerPluginSource(installations, packages), record


def test_exact_package_recovery_then_disable_reenable_drift_suspends() -> None:
    extension, source, record = _source()
    guard = prepare_worker_plugins(
        extension, source=source, skills_available=False, mcp_available=True
    )
    assert guard is not None
    source.installations.get_revision.assert_awaited_once_with(
        scope=SCOPE, installation_id=record.installation_id, revision=record.revision
    )
    source.packages.read.assert_awaited_once_with(record.package)
    guard.validate()
    for available in ((), (record.model_copy(update={"revision": 3}),)):
        source.installations.get_current_batch.return_value = available
        with pytest.raises(PluginAuthorityUnavailable):
            guard.validate()
    source.installations.get.assert_not_called()


def test_independent_direct_source_survives_without_trusting_revoked_plugin() -> None:
    extension, source, _ = _source(direct=True)
    source.installations.get_current_batch.return_value = ()
    guard = prepare_worker_plugins(
        extension, source=source, skills_available=False, mcp_available=True
    )
    guard.validate()
    assert not source.installations.mock_calls and not source.packages.mock_calls


def test_missing_worker_source_refuses_before_package_io() -> None:
    extension, source, _ = _source()
    with pytest.raises(PluginAuthorityUnavailable):
        prepare_worker_plugins(
            extension, source=source, skills_available=False, mcp_available=False
        )
    assert not source.installations.mock_calls and not source.packages.mock_calls


@pytest.mark.parametrize("stage", ["context", "gateway"])
def test_setup_authority_failure_suspends_open_turn_without_model(
    tmp_path, monkeypatch, stage
) -> None:
    from agent_core.domain.events import EventType
    from agent_core.domain.sessions import SessionStatus

    from tests.worker.execution.test_claimed_execution import _setup
    from tests.worker.execution.worker_execution_support import _created_at

    service, lease, leases = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        (
            "zebra_agent_worker.context_materialization.recover_turn_extension"
            if stage == "context"
            else "zebra_agent_worker.execution_tool_gateway.prepare_worker_plugins"
        ),
        Mock(side_effect=PluginAuthorityUnavailable("private credential detail")),
    )
    result = service.execute_claimed_session(lease, executed_at=_created_at())
    assert result.session.status is SessionStatus.SUSPENDED
    assert not any(
        e.event_type
        in {EventType.MODEL_REQUEST_STARTED, EventType.TURN_FAILED, EventType.SESSION_FAILED}
        for e in result.events
    )
    assert "private" not in str(result.attempt_result)
    assert leases.get(lease.session_id) is None


def test_control_signals_take_priority_over_plugin_unavailable() -> None:
    from concurrent.futures import CancelledError

    from agent_core.domain.leases import LeaseLostError

    extension, source, _ = _source()
    guard = prepare_worker_plugins(
        extension, source=source, skills_available=False, mcp_available=True
    )
    for error in (LeaseLostError("stale fence"), CancelledError()):
        source.installations.get_current_batch.side_effect = error
        with pytest.raises(type(error)):
            guard.validate()


def test_recovery_never_reads_latest_revision_package_after_rebind() -> None:
    extension, source, record = _source()
    source.installations.get_current_batch.return_value = (
        record.model_copy(update={"revision": 9}),
    )
    with pytest.raises(PluginAuthorityUnavailable):
        prepare_worker_plugins(extension, source=source, skills_available=False, mcp_available=True)
    source.installations.get_revision.assert_awaited_once_with(
        scope=SCOPE, installation_id=record.installation_id, revision=record.revision
    )
    source.packages.read.assert_not_awaited()
