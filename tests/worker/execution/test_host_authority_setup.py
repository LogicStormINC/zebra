"""Real Worker/SQLite startup journal refuses before input/model dispatch."""

from dataclasses import replace

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionError
from agent_core.domain.sessions import SessionStatus
from agent_storage import SQLiteEventStore
from worker_execution_support import _build_execution_service, _seed_ready_session
from zebra_agent_config.host_authority_settings import HostExecutionAuthoritySettings
from zebra_agent_worker.host_authority_probe import HostAuthorityUnavailable


@pytest.mark.parametrize(
    "error,reason",
    [
        (ExecutionAuthorityResolutionError("denied"), "host_authority_denied"),
        (HostAuthorityUnavailable("timeout"), "host_authority_unavailable"),
    ],
)
def test_early_refusal_suspends_original_session_without_preparing_input_or_model(
    tmp_path,
    monkeypatch,
    error,
    reason,
):
    database = tmp_path / "authority.db"
    session_id = _seed_ready_session(database, tmp_path)
    service = _build_execution_service(database)
    service._settings = replace(
        service._settings, host_execution_authority=HostExecutionAuthoritySettings(enabled=True)
    )

    def refuse(*_):
        raise error

    def forbidden(*_, **__):
        pytest.fail("private input/model must not be prepared")

    monkeypatch.setattr("zebra_agent_worker.execution.HostExecutionAuthority.for_execution", refuse)
    monkeypatch.setattr("zebra_agent_worker.execution.prepare_execution_inputs", forbidden)
    monkeypatch.setattr("zebra_agent_worker.execution.build_model_gateway", forbidden)
    result = service.execute_session(session_id, worker_id="authority-no-model")
    assert result.session.session_id == session_id
    assert result.session.status is SessionStatus.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == reason
    events = SQLiteEventStore(database).list_for_session(session_id)
    assert sum(e.event_type is EventType.SESSION_SUSPENDED for e in events) == 1
    assert not any(
        e.event_type
        in {EventType.MODEL_REQUEST_STARTED, EventType.TURN_COMPLETED, EventType.TURN_FAILED}
        for e in events
    )
