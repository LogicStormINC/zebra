from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId, new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.models import HarnessEventDraft
from agent_storage import ControlPlaneStores, sqlite_control_plane_stores
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import build_worker_loop_service
from zebra_agent_worker.context_lifecycle import persist_context_compaction
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.session_handoff import guard_effectful_tools
from zebra_agent_worker.tool_run_index import ToolRunIndexer


class _CountingGateway:
    model_tools = ()
    effective_mcp_tools = ()
    effective_skill_components = ()
    parallel_safe_tools = frozenset()
    parallel_batch_limits: dict[str, int] = {}

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="done",
        )

    def resolve_model_tool_calls(
        self,
        tool_calls: tuple[ToolCall, ...],
    ) -> tuple[ToolCall, ...]:
        return tool_calls

    def close(self) -> None:
        pass


def test_worker_uses_supplied_stores_for_all_control_plane_services(tmp_path: Path) -> None:
    control_database = tmp_path / "control-plane.db"
    legacy_database = tmp_path / "legacy.db"
    local = sqlite_control_plane_stores(control_database)
    event_store = Mock(wraps=local.events)
    projection_store = Mock(wraps=local.sessions)
    workspace_store = Mock(wraps=local.workspaces)
    task_store = Mock(wraps=local.tasks)
    lease_store = Mock(wraps=local.leases)
    stores = replace(
        local,
        events=event_store,
        sessions=projection_store,
        workspaces=workspace_store,
        tasks=task_store,
        leases=lease_store,
    )
    session_id = _seed_ready_session(stores, tmp_path)
    stores.leases.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(minutes=5),
        checkpoint=2,
    )
    for store in (event_store, projection_store, workspace_store, task_store, lease_store):
        store.reset_mock()

    service = build_worker_loop_service(
        database_path=legacy_database,
        settings=_settings(legacy_database),
        stores=stores,
        sleep=lambda _: None,
    )
    result = service.poll_once(worker_id="worker-b")

    assert result.ready_session_ids == (str(session_id),)
    assert result.skipped_session_ids == (str(session_id),)
    projection_store.list_ready_sessions.assert_called_once_with(limit=1)
    projection_store.get_session.assert_not_called()
    event_store.read_since.assert_not_called()
    workspace_store.get_workspace.assert_not_called()
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
    assert execution._model_call_indexer._model_call_store is stores.model_calls
    assert execution._artifact_payload_store is stores.artifact_payloads
    assert execution._context_lifecycle_store is stores.context_lifecycle
    assert execution._provider_continuation_store is stores.provider_continuations
    assert execution._tool_run_indexer._tool_run_store is stores.tool_runs
    assert execution._memory_extraction_service._memory_store is stores.memories
    assert execution._effect_ledger is stores.effects
    assert execution._session_history is stores.session_history
    assert execution._handoff_gate._events is stores.events
    assert execution._handoff_gate._sessions is stores.sessions
    assert execution._handoff_gate._workspaces is stores.workspaces
    assert execution._handoff_gate._handoffs is stores.handoffs
    assert execution._handoff_gate._dispatch is stores.handoff_dispatch

    assert not legacy_database.exists()
    legacy = sqlite_control_plane_stores(legacy_database)
    assert legacy.events.list_for_session(session_id) == []
    assert legacy.sessions.get_session(session_id) is None


def test_compaction_and_recovery_stay_on_authoritative_backend(tmp_path: Path) -> None:
    authority_path = tmp_path / "authority.db"
    legacy_path = tmp_path / "legacy.db"
    stores = sqlite_control_plane_stores(authority_path)
    session_id = _seed_ready_session(stores, tmp_path)
    recovery = SessionRecoveryService(
        stores.events,
        stores.sessions,
        stores.workspaces,
    ).recover_session(session_id)
    recorder = DurableHarnessEventRecorder(
        session=recovery.session,
        workspace=recovery.workspace,
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        model_call_indexer=ModelCallIndexer(stores.model_calls),
        tool_run_indexer=ToolRunIndexer(stores.tool_runs, stores.artifact_payloads),
    )
    capsule = ContextCapsule(
        capsule_id="authoritative-context",
        objective="Keep one durable stream.",
        constraints=("Do not write the legacy path.",),
        immediate_next="Continue from backend B.",
        source_hash="a" * 64,
        confidence=1.0,
        created_at=datetime(2026, 7, 24, 4, 0, tzinfo=UTC),
    )
    draft = HarnessEventDraft(
        event_type=EventType.CONTEXT_COMPACTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "before_tokens": 100,
            "after_tokens": 40,
            "removed_message_count": 3,
            "retained_message_count": 2,
            "within_budget": True,
            "provenance": "authoritative-composition-test",
            "capsule": capsule.model_dump(mode="json"),
        },
    )

    persist_context_compaction(
        draft,
        recorder=recorder,
        event_store=stores.events,
        lifecycle_store=stores.context_lifecycle,
    )

    events = stores.events.list_for_session(session_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.CONTEXT_COMPACTED,
        EventType.CONTEXT_CAPSULE_CREATED,
    ]
    active = stores.context_lifecycle.get_active_capsule(session_id)
    assert active is not None
    assert active.capsule.objective == "Keep one durable stream."
    session = stores.sessions.get_session(session_id)
    assert session is not None
    assert session.current_sequence == events[-1].sequence

    assert not legacy_path.exists()
    legacy = sqlite_control_plane_stores(legacy_path)
    assert legacy.events.list_for_session(session_id) == []
    assert legacy.context_lifecycle.get_active_capsule(session_id) is None


def test_effect_replay_uses_authoritative_backend(tmp_path: Path) -> None:
    authority_path = tmp_path / "authority.db"
    legacy_path = tmp_path / "legacy.db"
    stores = sqlite_control_plane_stores(authority_path)
    root_session_id = new_session_id()
    gateway = _CountingGateway()
    guarded = guard_effectful_tools(
        gateway,
        ledger=stores.effects,
        session_id=root_session_id,
        recovered_handoff=None,
        authority_scope="workspace-write",
    )

    first = guarded.execute(_effect_call())
    replayed = guarded.execute(_effect_call())

    assert replayed.output == first.output
    assert gateway.calls == 1
    assert stores.effects.terminal_keys(root_session_id)
    assert not legacy_path.exists()
    legacy = sqlite_control_plane_stores(legacy_path)
    assert legacy.effects.terminal_keys(root_session_id) == frozenset()


def _effect_call() -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": "deploy"},
        created_at=datetime(2026, 7, 24, 7, 0, tzinfo=UTC),
    )


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
