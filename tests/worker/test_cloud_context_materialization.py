from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationMode,
    ContextMaterializationRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.memories import MemoryQuery, MemoryRecord, MemoryVisibility
from agent_core.domain.session_history import SessionHistoryMessage
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.ports.context_compiler import RuntimeEvidenceInput
from agent_security import parse_network_profile
from zebra_agent_worker.context_materialization import materialize_worker_context
from zebra_agent_worker.execution_context import (
    CLOUD_CONTEXT_TOKEN_BUDGET,
    harness_task_for_recovered,
)
from zebra_agent_worker.task_recovery import RecoveredTask

NOW = datetime(2026, 8, 23, 13, 0, tzinfo=UTC)


class _RecordingContextStore:
    def __init__(self) -> None:
        self.request: ContextMaterializationRequest | None = None

    def materialize(self, request: ContextMaterializationRequest) -> ContextMaterialization:
        self.request = request
        return ContextMaterialization(
            request=request,
            session_revision=request.expected_session_revision,
            history=(
                SessionHistoryMessage(
                    sequence=1,
                    role="user",
                    content="Authoritative cloud task input.",
                    created_at=NOW,
                ),
            ),
        )


class _RecordingMemoryStore:
    def __init__(self) -> None:
        self.queries: list[MemoryQuery] = []

    def get(self, memory_id: object) -> MemoryRecord | None:
        del memory_id
        return None

    def list(self, query: MemoryQuery) -> list[MemoryRecord]:
        self.queries.append(query)
        return []


def _task(workspace_root: Path) -> RecoveredTask:
    return RecoveredTask(
        title="Cloud Context",
        user_input="Continue from authoritative state.",
        workspace_root=workspace_root.resolve(),
        policy_profile="read_only",
        tool_profile=ToolProfile.RESEARCH,
        network_profile=parse_network_profile("none"),
        mcp_allowlist=(),
        skill_components=(),
        history_session_ids=None,
        max_attempts=1,
        max_model_calls=None,
        max_tool_calls=None,
        attachments=(),
        runtime_evidence=(
            RuntimeEvidenceInput(
                kind="existing",
                summary="Existing bounded evidence",
            ),
        ),
        host_context=None,
        definition_snapshot=None,
    )


def test_cloud_worker_materializes_one_scoped_recent_context_generation(
    tmp_path: Path,
) -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cloud Context",
            user_input="Continue from authoritative state.",
            workspace_root=tmp_path.resolve(),
            created_at=NOW,
        )
    )
    scope = OpaqueAuthorityScope(
        authority_issuer="https://host.example.test",
        namespace_id="tenant-a",
        allowed_session_ids=(str(bootstrap.session.session_id),),
    )
    store = _RecordingContextStore()

    materialization = materialize_worker_context(
        store,
        scope=scope,
        session=bootstrap.session,
        task=_task(tmp_path),
        source_workspace_ref="workspace://tenant-a/repo-7",
        active_capsule_id=None,
        events=list(bootstrap.events),
        as_of=NOW,
    )

    assert materialization is not None
    request = store.request
    assert request is not None
    assert request.mode is ContextMaterializationMode.INITIAL
    assert request.expected_session_revision == bootstrap.session.current_sequence
    assert request.history_limit == 20
    assert request.memory_query is not None
    assert request.memory_query.repo_id == "workspace://tenant-a/repo-7"
    assert request.memory_query.visibility is MemoryVisibility.REPO
    assert request.memory_query.limit == 8


def test_cloud_harness_uses_materialized_inputs_and_keeps_local_baseline(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=task.title,
            user_input=task.user_input,
            workspace_root=tmp_path.resolve(),
            created_at=NOW,
        )
    )
    store = _RecordingContextStore()
    materialization = materialize_worker_context(
        store,
        scope=OpaqueAuthorityScope(
            authority_issuer="https://host.example.test",
            namespace_id="tenant-a",
            allowed_session_ids=(str(bootstrap.session.session_id),),
        ),
        session=bootstrap.session,
        task=task,
        source_workspace_ref="workspace://tenant-a/repo-7",
        active_capsule_id=None,
        events=list(bootstrap.events),
        as_of=NOW,
    )
    gateway = SimpleNamespace(effective_mcp_tools=(), effective_skill_components=())
    memory_store = _RecordingMemoryStore()

    cloud_task = harness_task_for_recovered(
        task,
        network_profile=task.network_profile,
        tool_gateway=gateway,
        memory_store=memory_store,
        materialization=materialization,
    )
    local_task = harness_task_for_recovered(
        task,
        network_profile=task.network_profile,
        tool_gateway=gateway,
        memory_store=memory_store,
    )

    assert cloud_task.context_token_budget == CLOUD_CONTEXT_TOKEN_BUDGET
    assert {item.kind for item in cloud_task.runtime_evidence} == {
        "existing",
        "materialized_context",
    }
    assert local_task.context_token_budget == 200
    assert len(memory_store.queries) == 2


def test_automation_handoff_seed_does_not_count_as_conversation_history(
    tmp_path: Path,
) -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cloud Context",
            user_input="Continue from authoritative state.",
            workspace_root=tmp_path.resolve(),
            created_at=NOW,
        )
    )
    seed = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={
            "content": "Continue from the verified Task checkpoint.",
            "source": "session_handoff",
            "handoff_id": "0b944a26-7b9e-4d43-8d1f-9db2b0bd0ba5",
            "principal_identity_hash": "0f" * 32,
            "actor_kind": "automation",
            "trust": "automation",
        },
        created_at=NOW,
    )
    store = _RecordingContextStore()

    materialization = materialize_worker_context(
        store,
        scope=OpaqueAuthorityScope(
            authority_issuer="https://host.example.test",
            namespace_id="tenant-a",
            allowed_session_ids=(str(bootstrap.session.session_id),),
        ),
        session=bootstrap.session,
        task=_task(tmp_path),
        source_workspace_ref="workspace://tenant-a/repo-7",
        active_capsule_id=None,
        events=[*bootstrap.events, seed],
        as_of=NOW,
    )

    assert materialization is not None
    assert store.request is not None
    assert store.request.mode is ContextMaterializationMode.INITIAL
