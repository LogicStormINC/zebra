from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_storage import ControlPlaneStores, sqlite_control_plane_stores
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import SessionExecutionService, build_worker_loop_service
from zebra_agent_worker.session_handoff import SessionHandoffRecoveryGate


def test_worker_uses_supplied_stores_for_all_control_plane_services(tmp_path: Path) -> None:
    control_database = tmp_path / "control-plane.db"
    local = sqlite_control_plane_stores(control_database)
    event_store = Mock(wraps=local.events)
    projection_store = Mock(wraps=local.sessions)
    workspace_store = Mock(wraps=local.workspaces)
    task_store = Mock(wraps=local.tasks)
    lease_store = Mock(wraps=local.leases)
    stores = ControlPlaneStores(
        events=event_store,
        sessions=projection_store,
        workspaces=workspace_store,
        tasks=task_store,
        leases=lease_store,
        legacy_database_path=control_database.resolve(),
    )
    session_id = _seed_ready_session(stores, tmp_path)
    leased_at = datetime.now(UTC)
    stores.leases.acquire(
        session_id,
        worker_id="worker-a",
        acquired_at=leased_at,
        expires_at=leased_at + timedelta(minutes=5),
        checkpoint=2,
    )
    for store in (event_store, projection_store, workspace_store, task_store, lease_store):
        store.reset_mock()

    service = build_worker_loop_service(
        database_path=control_database,
        settings=_settings(control_database),
        stores=stores,
        sleep=lambda _: None,
    )
    result = service.poll_once(worker_id="worker-b")

    assert result.ready_session_ids == (str(session_id),)
    assert result.skipped_session_ids == (str(session_id),)
    projection_store.list_ready_sessions.assert_called_once_with(limit=1)
    projection_store.get_session.assert_called_once_with(session_id)
    assert event_store.read_since.call_count >= 1
    workspace_store.get_workspace.assert_called_once_with(session_id)
    lease_store.acquire.assert_called_once()
    assert service._projection_store is stores.sessions
    execution = service._execution_service
    assert execution._claim_service._lease_store is stores.leases
    recovery = execution._claim_service._recovery_service
    assert recovery._event_store is stores.events
    assert recovery._projection_store is stores.sessions
    assert recovery._workspace_store is stores.workspaces
    assert execution._event_store is stores.events
    assert execution._projection_store is stores.sessions
    assert execution._workspace_store is stores.workspaces
    assert execution._control_service._event_store is stores.events
    assert execution._control_service._projection_store is stores.sessions
    assert execution._control_service._workspace_store is stores.workspaces
    assert execution._handoff_gate._events is stores.events
    assert execution._handoff_gate._sessions is stores.sessions
    assert execution._handoff_gate._workspaces is stores.workspaces


def test_worker_rejects_partial_split_backend(tmp_path: Path) -> None:
    control_database = tmp_path / "control-plane.db"
    runtime_database = tmp_path / "runtime-local.db"

    with pytest.raises(ValueError, match="must share database_path"):
        build_worker_loop_service(
            database_path=runtime_database,
            settings=_settings(runtime_database),
            stores=sqlite_control_plane_stores(control_database),
            sleep=lambda _: None,
        )

    assert not runtime_database.exists()


def test_worker_lifecycle_roots_reject_partial_split_backend(tmp_path: Path) -> None:
    control_database = tmp_path / "control-plane.db"
    runtime_database = tmp_path / "runtime-local.db"
    stores = sqlite_control_plane_stores(control_database)

    with pytest.raises(ValueError, match="must share database_path"):
        SessionExecutionService(
            database_path=runtime_database,
            claim_service=Mock(),
            resume_service=Mock(),
            settings=_settings(runtime_database),
            stores=stores,
        )
    with pytest.raises(ValueError, match="must share database_path"):
        SessionHandoffRecoveryGate(str(runtime_database), stores=stores)

    assert not runtime_database.exists()


def _seed_ready_session(
    stores: ControlPlaneStores,
    workspace_root: Path,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued worker task",
            user_input="Continue the queued task.",
            workspace_root=workspace_root.resolve(),
        )
    )
    for event in bootstrap.events:
        stores.events.append(event)
    stores.sessions.save_session(bootstrap.session)
    return bootstrap.session.session_id


def _settings(database_path: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )
