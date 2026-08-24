from datetime import UTC, datetime
from uuid import UUID

import pytest
from agent_context import (
    context_inputs_from_delegated_snapshot,
    context_inputs_from_materialization,
    delegated_context_from_materialization,
)
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_inheritance import ContextInheritanceMode
from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationRequest,
)
from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.session_history import SessionHistoryMessage

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
SESSION_ID = SessionId(UUID("00000000-0000-0000-0000-000000000102"))


def _materialization(
    *, capsule: bool = True, history_truncated: bool = False
) -> ContextMaterialization:
    active = (
        ContextCapsule(
            capsule_id="capsule-7",
            objective="Preserve the verified parent objective.",
            acceptance_criteria=("child cites evidence",),
            constraints=("read only",),
            decisions=("PostgreSQL is authoritative",),
            touched_files=("README.md",),
            tests=("make check passed",),
            errors=("one prior timeout",),
            artifact_refs=("artifact://evidence/1",),
            open_questions=("which Trench endpoint",),
            immediate_next="inspect the deployment runbook",
            source_hash="a" * 64,
            confidence=1.0,
            created_at=NOW,
        )
        if capsule
        else None
    )
    memory = MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000202")),
        memory_type=MemoryType.PROJECT_RULE,
        text="Use the confirmed PostgreSQL authority.",
        confidence=1.0,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.REPO,
        repo_id="repo-1",
        created_at=NOW,
        updated_at=NOW,
    )
    request = ContextMaterializationRequest(
        scope=OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="namespace",
            allowed_session_ids=(str(SESSION_ID),),
        ),
        session_id=SESSION_ID,
        expected_session_revision=7,
        expected_active_capsule_id=None if active is None else active.capsule_id,
        as_of=NOW,
        memory_query=MemoryQuery(
            repo_id="repo-1",
            visibility=MemoryVisibility.REPO,
            statuses=(MemoryStatus.CONFIRMED,),
        ),
    )
    return ContextMaterialization(
        request=request,
        session_revision=7,
        history=(
            SessionHistoryMessage(1, "user", "old objective", NOW, False),
            SessionHistoryMessage(6, "assistant", "latest verified answer", NOW, False),
        ),
        history_truncated=history_truncated,
        active_capsule=active,
        memories=(
            GovernedMemoryEntry(
                deployment_namespace="cloud",
                record=memory,
                revision=2,
                creation_key=canonical_governed_memory_creation_key(memory),
                content_digest=canonical_governed_memory_content_hash(memory),
            ),
        ),
    )


def test_builder_implements_all_four_bounded_modes() -> None:
    materialized = _materialization()

    assert (
        delegated_context_from_materialization(
            materialized, ContextInheritanceMode.FRESH, created_at=NOW
        )
        is None
    )
    capsule = delegated_context_from_materialization(
        materialized, ContextInheritanceMode.CAPSULE, created_at=NOW
    )
    tail = delegated_context_from_materialization(
        materialized, ContextInheritanceMode.FORK_TAIL, created_at=NOW
    )
    resumed = delegated_context_from_materialization(
        materialized, ContextInheritanceMode.RESUME, created_at=NOW
    )

    assert capsule is not None and {item.kind for item in capsule.items} == {"capsule"}
    assert tail is not None and {item.kind for item in tail.items} == {"history"}
    assert resumed is not None and {item.kind for item in resumed.items} == {
        "capsule",
        "history",
        "memory",
    }
    assert resumed.checksum == resumed.expected_checksum()


def test_capsule_mode_never_silently_degrades_to_history() -> None:
    with pytest.raises(ValueError, match="active Context Capsule"):
        delegated_context_from_materialization(
            _materialization(capsule=False),
            ContextInheritanceMode.CAPSULE,
            created_at=NOW,
        )


def test_materialized_and_delegated_inputs_preserve_provenance() -> None:
    materialized = _materialization()
    snapshot = delegated_context_from_materialization(
        materialized, ContextInheritanceMode.RESUME, created_at=NOW
    )
    assert snapshot is not None

    materialized_inputs = context_inputs_from_materialization(materialized)
    delegated_inputs = context_inputs_from_delegated_snapshot(snapshot)

    assert materialized_inputs.runtime_evidence[0].kind == "materialized_context"
    assert delegated_inputs.runtime_evidence[0].kind == "delegated_context"
    assert delegated_inputs.runtime_evidence[0].metadata["checksum"] == snapshot.checksum
    assert delegated_inputs.confirmed_memories[0].text == (
        "Use the confirmed PostgreSQL authority."
    )
    rendered = "\n".join(delegated_inputs.runtime_evidence[0].details)
    assert "context-capsule://capsule-7" in rendered
    assert f"session-event://{SESSION_ID}/6" in rendered


def test_truncated_history_without_capsule_records_uncovered_prefix() -> None:
    snapshot = delegated_context_from_materialization(
        _materialization(capsule=False, history_truncated=True),
        ContextInheritanceMode.RESUME,
        created_at=NOW,
    )
    assert snapshot is not None

    assert "history_tail_truncated" in snapshot.known_omissions
    assert "history_prefix_uncovered" in snapshot.known_omissions


def test_truncated_history_with_capsule_keeps_prefix_covered() -> None:
    snapshot = delegated_context_from_materialization(
        _materialization(capsule=True, history_truncated=True),
        ContextInheritanceMode.RESUME,
        created_at=NOW,
    )
    assert snapshot is not None

    assert "history_tail_truncated" in snapshot.known_omissions
    assert "history_prefix_uncovered" not in snapshot.known_omissions
