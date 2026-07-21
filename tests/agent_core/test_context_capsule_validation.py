from datetime import UTC, datetime

import pytest
from agent_core.contracts.events import event_payload_schema_for
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextCapsuleValidationError,
    ContextSourceEventRange,
    PendingToolState,
    validate_context_capsule,
)
from agent_core.domain.events import EventType


def test_context_capsule_validator_protects_durable_state() -> None:
    capsule = _capsule()
    context = ContextCapsuleValidationContext(
        expected_source_hash="a" * 64,
        expected_source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=9),
        unresolved_tool_call_ids=frozenset({"call-1"}),
        protected_user_constraints=frozenset({"do not push"}),
        approval_and_policy_state=frozenset({"write:approved"}),
        readable_artifact_refs=frozenset({"artifact://evidence"}),
    )

    validate_context_capsule(capsule, context)

    with pytest.raises(ContextCapsuleValidationError, match="protected user constraints"):
        validate_context_capsule(
            capsule.model_copy(update={"protected_user_constraints": ()}), context
        )


def test_context_capsule_validator_uses_recent_exact_tail_refs() -> None:
    capsule = _capsule().model_copy(
        update={"recent_exact_tail_refs": ("event://session/1", "artifact://recent")}
    )
    context = ContextCapsuleValidationContext(
        expected_source_hash="a" * 64,
        expected_source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=9),
        unresolved_tool_call_ids=frozenset({"call-1"}),
        protected_user_constraints=frozenset({"do not push"}),
        approval_and_policy_state=frozenset({"write:approved"}),
        readable_artifact_refs=frozenset(
            {"artifact://evidence", "event://session/1", "artifact://recent"}
        ),
    )

    validate_context_capsule(capsule, context)


def test_context_capsule_validator_normalizes_artifact_refs_for_readability_check() -> None:
    capsule = _capsule().model_copy(
        update={
            "artifact_refs": (
                "artifact://evidence\",",
                "artifact://stale\",)",
            ),
            "recent_exact_tail_refs": ("event://session/1\",", "artifact://recent"),
        }
    )
    context = ContextCapsuleValidationContext(
        expected_source_hash="a" * 64,
        expected_source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=9),
        unresolved_tool_call_ids=frozenset({"call-1"}),
        protected_user_constraints=frozenset({"do not push"}),
        approval_and_policy_state=frozenset({"write:approved"}),
        readable_artifact_refs=frozenset(
            {
                "artifact://evidence",
                "artifact://stale",
                "event://session/1",
                "artifact://recent",
            }
        ),
    )
    capsule = ContextCapsule.model_validate(capsule.model_dump())

    validate_context_capsule(capsule, context)


def test_context_capsule_created_event_has_a_strict_contract() -> None:
    schema = event_payload_schema_for(EventType.CONTEXT_CAPSULE_CREATED)

    assert schema["additionalProperties"] is False
    assert "artifact_id" in schema["required"]
    assert "source_event_range" in schema["required"]


def _capsule() -> ContextCapsule:
    return ContextCapsule(
        capsule_id="ctxcap-1",
        objective="Finish compaction",
        protected_user_constraints=("do not push",),
        approvals_and_policy_state=("write:approved",),
        pending_tools=(PendingToolState(call_id="call-1", name="command"),),
        artifact_refs=("artifact://evidence",),
        immediate_next="Run tests",
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=9),
        source_hash="a" * 64,
        confidence=1.0,
        created_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
    )
