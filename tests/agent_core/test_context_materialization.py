from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationMode,
    ContextMaterializationRequest,
)
from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import AgentDefinitionId, MemoryId, SessionId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.session_history import SessionHistoryMessage

SESSION_ID = SessionId(UUID("00000000-0000-0000-0000-000000000001"))
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def test_request_requires_scope_and_confirmed_memory_query() -> None:
    scope = OpaqueAuthorityScope(
        authority_issuer="issuer",
        namespace_id="namespace",
        allowed_session_ids=(str(SESSION_ID),),
    )
    request = ContextMaterializationRequest(
        scope=scope,
        session_id=SESSION_ID,
        expected_session_revision=2,
        as_of=NOW,
        mode=ContextMaterializationMode.CONTINUE,
        expected_active_capsule_id="capsule-2",
        memory_query=MemoryQuery(
            repo_id="repo-1",
            visibility=MemoryVisibility.REPO,
            text_query="postgres",
            limit=2,
        ),
    )
    assert request.expected_active_capsule_id == "capsule-2"

    with pytest.raises(ValueError, match="confirmed Memory"):
        ContextMaterializationRequest(
            scope=scope,
            session_id=SESSION_ID,
            expected_session_revision=2,
            as_of=NOW,
            memory_query=MemoryQuery(
                repo_id="repo-1",
                visibility=MemoryVisibility.REPO,
                statuses=(MemoryStatus.CANDIDATE,),
            ),
        )

    with pytest.raises(ValueError, match="outside the read scope"):
        ContextMaterializationRequest(
            scope=OpaqueAuthorityScope(
                authority_issuer="issuer",
                namespace_id="namespace",
                allowed_session_ids=(),
            ),
            session_id=SESSION_ID,
            expected_session_revision=0,
            as_of=NOW,
        )


def test_materialization_generation_is_revisioned_and_rebuildable() -> None:
    request = _request(expected_session_revision=4, capsule_id="capsule-4")
    memory = _memory(revision=3)
    materialization = ContextMaterialization(
        request=request,
        session_revision=4,
        history=(
            SessionHistoryMessage(1, "user", "start", NOW, False),
            SessionHistoryMessage(4, "assistant", "done", NOW, False),
        ),
        active_capsule=_capsule("capsule-4"),
        memories=(memory,),
    )

    assert materialization.generation.session_revision == 4
    assert materialization.generation.active_capsule_id == "capsule-4"
    assert materialization.generation.memory_revisions == ((str(memory.record.memory_id), 3),)
    assert (
        materialization.generation
        == ContextMaterialization(
            request=request,
            session_revision=4,
            history=materialization.history,
            active_capsule=materialization.active_capsule,
            memories=materialization.memories,
        ).generation
    )


def test_materialization_rejects_stale_capsule_duplicate_and_expired_memory() -> None:
    request = _request(expected_session_revision=4, capsule_id="capsule-4")
    with pytest.raises(ValueError, match="active Capsule is stale"):
        ContextMaterialization(
            request=request,
            session_revision=4,
            active_capsule=_capsule("capsule-old"),
        )

    memory = _memory(revision=1)
    with pytest.raises(ValueError, match="IDs must be unique"):
        ContextMaterialization(
            request=request,
            session_revision=4,
            active_capsule=_capsule("capsule-4"),
            memories=(memory, memory),
        )

    expired = _memory(revision=2, expires_at=NOW)
    with pytest.raises(ValueError, match="expired Memory"):
        ContextMaterialization(
            request=request,
            session_revision=4,
            active_capsule=_capsule("capsule-4"),
            memories=(expired,),
        )


def test_materialization_rejects_memory_from_another_definition_scope() -> None:
    definition_id = AgentDefinitionId(UUID(int=201))
    request = ContextMaterializationRequest(
        scope=OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="namespace",
            allowed_session_ids=(str(SESSION_ID),),
        ),
        session_id=SESSION_ID,
        expected_session_revision=4,
        as_of=NOW,
        memory_query=MemoryQuery(
            authority_issuer="issuer",
            namespace_id="namespace",
            definition_id=definition_id,
            limit=4,
        ),
    )
    record = MemoryRecord(
        memory_id=MemoryId(UUID(int=202)),
        memory_type=MemoryType.PROJECT_RULE,
        text="This belongs to another Definition.",
        confidence=1.0,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.REPO,
        authority_issuer="issuer",
        namespace_id="namespace",
        definition_id=AgentDefinitionId(UUID(int=203)),
        created_at=NOW - timedelta(minutes=2),
        updated_at=NOW - timedelta(minutes=1),
    )
    memory = GovernedMemoryEntry(
        deployment_namespace="deployment",
        record=record,
        revision=1,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=canonical_governed_memory_content_hash(record),
    )

    with pytest.raises(ValueError, match="visibility scope"):
        ContextMaterialization(
            request=request,
            session_revision=4,
            memories=(memory,),
        )


def _request(
    *, expected_session_revision: int, capsule_id: str | None
) -> ContextMaterializationRequest:
    return ContextMaterializationRequest(
        scope=OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="namespace",
            allowed_session_ids=(str(SESSION_ID),),
        ),
        session_id=SESSION_ID,
        expected_session_revision=expected_session_revision,
        as_of=NOW,
        expected_active_capsule_id=capsule_id,
        memory_query=MemoryQuery(repo_id="repo-1", visibility=MemoryVisibility.REPO, limit=4),
    )


def _capsule(capsule_id: str) -> ContextCapsule:
    return ContextCapsule(
        capsule_id=capsule_id,
        objective="keep the cloud Context boundary explicit",
        immediate_next="read the next source",
        source_hash="a" * 64,
        confidence=1.0,
        created_at=NOW,
    )


def _memory(*, revision: int, expires_at: datetime | None = None) -> GovernedMemoryEntry:
    record = MemoryRecord(
        memory_id=MemoryId(UUID(int=revision + 10)),
        memory_type=MemoryType.PROJECT_RULE,
        text="PostgreSQL is the cloud fact source",
        confidence=1.0,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.REPO,
        repo_id="repo-1",
        expires_at=expires_at,
        created_at=NOW - timedelta(minutes=2),
        updated_at=NOW - timedelta(minutes=1),
    )
    return GovernedMemoryEntry(
        deployment_namespace="deployment",
        record=record,
        revision=revision,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=canonical_governed_memory_content_hash(record),
    )
