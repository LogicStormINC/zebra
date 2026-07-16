from pathlib import Path

from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_runs import ToolRunRecord
from agent_security import LocalPolicyEngine, NetworkProfile
from agent_storage import (
    SQLiteLeaseStore,
    SQLiteModelCallStore,
    SQLiteToolRunStore,
)
from worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
    _created_at,
    _seed_ready_session,
    _seed_ready_session_with_input,
    _tool_gateway,
)


def test_worker_execution_service_completes_ready_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "Worker completed the session."
    assert SQLiteLeaseStore(database_path).get(session_id) is None
    model_calls = SQLiteModelCallStore(database_path).list_for_session(session_id)
    assert len(model_calls) == 1
    assert isinstance(model_calls[0], ModelCallRecord)

def test_worker_execution_recovers_network_authority(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session_with_input(
        database_path,
        tmp_path,
        user_input="Continue with bounded network authority.",
        network_profile="domain-allowlist",
        network_allowlist=("docs.example.com",),
    )
    captured: list[NetworkProfile] = []

    def build_policy(*, profile, network_profile, web_search_endpoint):
        captured.append(network_profile)
        assert web_search_endpoint is None
        return LocalPolicyEngine(profile=profile, network_profile=network_profile)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    monkeypatch.setattr("zebra_agent_worker.execution.LocalPolicyEngine", build_policy)

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-network",
        executed_at=_created_at(),
    )

    assert captured[0].name.value == "domain-allowlist"
    assert captured[0].domain_allowlist == ("docs.example.com",)

def test_worker_execution_service_indexes_tool_run(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "worker.db"
    (tmp_path / "README.md").write_text("worker readme\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _tool_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    tool_runs = SQLiteToolRunStore(database_path).list_for_session(session_id)
    assert result.session.status is SessionStatus.COMPLETED
    assert len(tool_runs) == 1
    assert isinstance(tool_runs[0], ToolRunRecord)
    assert tool_runs[0].tool_name == "files.read"
    assert tool_runs[0].status == "executed"
    assert tool_runs[0].artifact_uri is not None
    assert Path(tool_runs[0].artifact_uri.removeprefix("file://")).read_text(
        encoding="utf-8"
    ) == "worker readme\n"
