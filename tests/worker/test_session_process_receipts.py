"""No model: bounded private failure proof, lease identity and terminal classification."""

import json
from uuid import uuid4

import pytest
from agent_core.domain.sessions import SessionStatus
from zebra_agent_worker.execution_errors import (
    WorkerExecutorInterrupted,
    WorkerInputPreparationUnavailable,
)
from zebra_agent_worker.session_process import require_input_failure, write_input_failure


def request():
    return {
        "session_id": str(uuid4()),
        "lease": {
            "fence": {
                "fencing_token": 1,
                "owner_instance_id": "worker",
                "control_plane_epoch": str(uuid4()),
            }
        },
    }


def test_exact_failure_receipt_is_atomic_bounded_and_does_not_expose_input(tmp_path):
    value = request()
    value["user_input"] = "must not appear in IPC"
    result = tmp_path / "result.json"
    write_input_failure(result, value)
    assert not result.with_suffix(".error.tmp").exists()
    assert "must not appear" not in result.with_suffix(".error.json").read_text()
    with pytest.raises(WorkerInputPreparationUnavailable):
        require_input_failure(result, value)


@pytest.mark.parametrize(
    "change", ["session", "fence", "extra", "oversize", "malformed", "success", "bool_fence"]
)
def test_conflicting_truncated_or_oversize_proof_stays_uncertain(tmp_path, change):
    value = request()
    result = tmp_path / "result.json"
    write_input_failure(result, value)
    path = result.with_suffix(".error.json")
    payload = json.loads(path.read_text())
    if change == "session":
        payload["session_id"] = str(uuid4())
    elif change == "fence":
        payload["fence"]["fencing_token"] += 1
    elif change == "extra":
        payload["error"] = "arbitrary exception"
    elif change == "bool_fence":
        payload["fence"]["fencing_token"] = True
    elif change == "success":
        result.write_text("{}")
    path.write_text(
        "x" * 2049
        if change == "oversize"
        else "{"
        if change == "malformed"
        else json.dumps(payload)
    )
    with pytest.raises(WorkerExecutorInterrupted):
        require_input_failure(result, value)


def test_missing_proof_is_not_a_known_startup_failure(tmp_path):
    require_input_failure(tmp_path / "result.json", request())


def test_pre_model_child_failure_retains_suspended_turn_and_never_calls_model(
    tmp_path, monkeypatch
):
    from tests.worker.execution.worker_execution_support import (
        _build_execution_service,
        _seed_ready_session,
    )

    path = tmp_path / "session.db"
    sid = _seed_ready_session(path, tmp_path)
    service = _build_execution_service(path)
    monkeypatch.setattr("zebra_agent_worker.execution.process_factory", lambda _: "default")

    def refuse(*args, **kwargs):
        raise WorkerInputPreparationUnavailable("execution_input_unavailable")

    def forbidden(*args, **kwargs):
        raise AssertionError("must not dispatch a model")

    monkeypatch.setattr("zebra_agent_worker.execution.execute_isolated", refuse)
    monkeypatch.setattr("zebra_agent_worker.execution.build_model_gateway", forbidden)
    result = service.execute_session(sid, worker_id="parent")
    assert result.session.status is SessionStatus.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "execution_input_unavailable"
    assert result.attempt_result.metadata["retryable"] is False
    assert service._projection_store.list_ready_sessions(limit=10) == []


def test_shared_preparation_boundary_classifies_real_resolver_failure(tmp_path, monkeypatch):
    from tests.worker.execution.worker_execution_support import (
        _build_execution_service,
        _seed_ready_session,
    )

    path = tmp_path / "input.db"
    sid = _seed_ready_session(path, tmp_path)
    service = _build_execution_service(path)
    service._workspace_resolver = object()

    def unavailable(*args, **kwargs):
        raise ValueError("sensitive allocator details")

    def forbidden(*args, **kwargs):
        raise AssertionError("must not call model")

    monkeypatch.delenv("ZEBRA_SESSION_PROCESS_FACTORY", raising=False)
    monkeypatch.setattr(
        "zebra_agent_worker.execution_recovery.apply_workspace_resolver", unavailable
    )
    monkeypatch.setattr("zebra_agent_worker.execution.build_model_gateway", forbidden)
    result = service.execute_session(sid, worker_id="in-process")
    assert result.session.status is SessionStatus.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "execution_input_unavailable"
    assert "sensitive allocator" not in json.dumps(result.attempt_result.metadata)
