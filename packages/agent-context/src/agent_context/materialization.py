"""Translate authoritative Context reads into bounded model and child inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_inheritance import (
    REQUIRED_CONTEXT_OMISSIONS,
    ContextInheritanceMode,
    DelegatedContextItem,
    DelegatedContextSnapshot,
)
from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput

MAX_INHERITED_HISTORY = 12
MAX_INHERITED_MEMORIES = 8
MAX_CAPSULE_CHARS = 6_000
MAX_MEMORY_CHARS = 1_600


@dataclass(frozen=True, slots=True)
class MaterializedContextInputs:
    runtime_evidence: tuple[RuntimeEvidenceInput, ...]
    confirmed_memories: tuple[ConfirmedMemoryInput, ...]


def delegated_context_from_materialization(
    materialization: ContextMaterialization,
    mode: ContextInheritanceMode,
    *,
    created_at: datetime,
) -> DelegatedContextSnapshot | None:
    """Select one explicit inheritance shape from trusted parent facts."""

    if mode is ContextInheritanceMode.FRESH:
        return None
    capsule = materialization.active_capsule
    history = materialization.history[-MAX_INHERITED_HISTORY:]
    memories = materialization.memories[:MAX_INHERITED_MEMORIES]
    if mode is ContextInheritanceMode.CAPSULE and capsule is None:
        raise ValueError("capsule context_mode requires an active Context Capsule")
    if mode is ContextInheritanceMode.FORK_TAIL and not history:
        raise ValueError("fork_tail context_mode requires bounded Session History")
    if mode is ContextInheritanceMode.RESUME and not (capsule or history or memories):
        raise ValueError("resume context_mode requires materialized continuity inputs")

    items: list[DelegatedContextItem] = []
    omissions = set(REQUIRED_CONTEXT_OMISSIONS)
    if mode in {ContextInheritanceMode.CAPSULE, ContextInheritanceMode.RESUME} and capsule:
        capsule_content, capsule_truncated = _capsule_content(capsule)
        items.append(
            DelegatedContextItem(
                kind="capsule",
                locator=f"context-capsule://{capsule.capsule_id}",
                content=capsule_content,
            )
        )
        if capsule_truncated:
            omissions.add("capsule_content_truncated")
    if mode in {ContextInheritanceMode.FORK_TAIL, ContextInheritanceMode.RESUME}:
        for message in history:
            items.append(
                DelegatedContextItem(
                    kind="history",
                    locator=(
                        f"session-event://{materialization.request.session_id}/{message.sequence}"
                    ),
                    content=f"{message.role}: {message.content}",
                    source_sequence=message.sequence,
                )
            )
        if len(materialization.history) > len(history) or materialization.history_truncated:
            omissions.add("history_tail_truncated")
        if materialization.history_truncated and capsule is None:
            # Older conversation exists but no Capsule covers it: the prefix is
            # uncovered. Record it explicitly; it must never vanish silently.
            omissions.add("history_prefix_uncovered")
        if any(message.text_truncated for message in history):
            omissions.add("source_history_text_truncated")
    if mode is ContextInheritanceMode.RESUME:
        for entry in memories:
            text, truncated = _bounded(entry.record.text, MAX_MEMORY_CHARS)
            items.append(
                DelegatedContextItem(
                    kind="memory",
                    locator=f"confirmed-memory://{entry.record.memory_id}@{entry.revision}",
                    content=text,
                    memory_type=entry.record.memory_type,
                )
            )
            if truncated:
                omissions.add("memory_content_truncated")
        if len(materialization.memories) > len(memories):
            omissions.add("memory_result_truncated")

    selected_memories = memories if mode is ContextInheritanceMode.RESUME else ()
    return DelegatedContextSnapshot.create(
        mode=mode,
        source_session_id=materialization.request.session_id,
        source_session_revision=materialization.session_revision,
        active_capsule_id=(
            capsule.capsule_id
            if capsule is not None
            and mode in {ContextInheritanceMode.CAPSULE, ContextInheritanceMode.RESUME}
            else None
        ),
        memory_revisions=tuple(
            sorted((str(entry.record.memory_id), entry.revision) for entry in selected_memories)
        ),
        items=tuple(items),
        known_omissions=tuple(sorted(omissions)),
        created_at=created_at,
    )


def context_inputs_from_materialization(
    materialization: ContextMaterialization,
) -> MaterializedContextInputs:
    snapshot = delegated_context_from_materialization(
        materialization,
        ContextInheritanceMode.RESUME,
        created_at=materialization.request.as_of,
    )
    assert snapshot is not None
    inputs = context_inputs_from_delegated_snapshot(snapshot)
    evidence = inputs.runtime_evidence[0]
    return MaterializedContextInputs(
        runtime_evidence=(
            RuntimeEvidenceInput(
                kind="materialized_context",
                summary="Authoritative bounded Context materialization",
                details=evidence.details,
                metadata={
                    **(evidence.metadata or {}),
                    "generation": {
                        "session_revision": materialization.generation.session_revision,
                        "active_capsule_id": materialization.generation.active_capsule_id,
                        "memory_revisions": materialization.generation.memory_revisions,
                    },
                },
            ),
        ),
        confirmed_memories=inputs.confirmed_memories,
    )


def context_inputs_from_delegated_snapshot(
    snapshot: DelegatedContextSnapshot,
) -> MaterializedContextInputs:
    continuity = tuple(item for item in snapshot.items if item.kind != "memory")
    runtime_evidence = (
        (
            RuntimeEvidenceInput(
                kind="delegated_context",
                summary=f"Bounded parent Context ({snapshot.mode.value})",
                details=tuple(
                    f"[{item.kind}] {item.locator}\n{item.content}" for item in continuity
                ),
                metadata={
                    "checksum": snapshot.checksum,
                    "source_session_id": str(snapshot.source_session_id),
                    "source_session_revision": snapshot.source_session_revision,
                    "active_capsule_id": snapshot.active_capsule_id,
                    "known_omissions": list(snapshot.known_omissions),
                },
            ),
        )
        if continuity
        else ()
    )
    memories = tuple(
        ConfirmedMemoryInput(memory_type=item.memory_type, text=item.content)
        for item in snapshot.items
        if item.kind == "memory" and item.memory_type is not None
    )
    return MaterializedContextInputs(runtime_evidence, memories)


def _capsule_content(capsule: ContextCapsule) -> tuple[str, bool]:
    sections: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Objective", (capsule.objective,)),
        ("Acceptance", capsule.acceptance_criteria),
        ("Scope", capsule.scope),
        ("Constraints", (*capsule.constraints, *capsule.protected_user_constraints)),
        (
            "Decisions",
            capsule.decisions_and_rationale or capsule.decisions,
        ),
        ("Plan", capsule.plan),
        ("Touched files", capsule.touched_files),
        ("Validation", capsule.tests),
        ("Known failures", capsule.errors),
        (
            "Pending tools",
            tuple(f"{tool.name} ({tool.call_id})" for tool in capsule.pending_tools),
        ),
        ("Artifacts", capsule.artifact_refs),
        ("Approvals and policy", capsule.approvals_and_policy_state),
        ("Open questions", capsule.open_questions),
        ("Immediate next", (capsule.immediate_next,)),
        ("Known omissions", capsule.known_omissions),
    )
    content = "\n".join(
        f"{title}:\n" + "\n".join(f"- {value}" for value in values if value.strip())
        for title, values in sections
        if any(value.strip() for value in values)
    )
    return _bounded(content, MAX_CAPSULE_CHARS)


def _bounded(value: str, maximum: int) -> tuple[str, bool]:
    value = value.strip()
    if len(value) <= maximum:
        return value, False
    return value[: maximum - 3].rstrip() + "...", True
