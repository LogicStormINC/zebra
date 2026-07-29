from datetime import UTC, datetime

from agent_context import (
    HandoffEnvelopeBuildInput,
    build_handoff_envelope,
    handoff_runtime_evidence,
)
from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.identifiers import new_handoff_id, new_session_id
from agent_core.domain.session_handoff import HandoffReason, WorkspaceBindingRevision


def test_builder_checksums_public_facts_and_runtime_evidence_is_bounded() -> None:
    source = new_session_id()
    target = new_session_id()
    envelope = build_handoff_envelope(
        HandoffEnvelopeBuildInput(
            handoff_id=new_handoff_id(),
            source_session_id=source,
            target_session_id=target,
            root_session_id=source,
            source_stage_index=0,
            reason=HandoffReason.USER_PHASE_BOUNDARY,
            objective="Implement the next phase",
            completed_work=("contracts merged",),
            pending_work=("worker gate",),
            immediate_next="run focused tests",
            source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=10),
            source_event_hash="event-hash",
            workspace_revision=WorkspaceBindingRevision(
                workspace_id="/repo", revision_hash="workspace-hash"
            ),
            created_at=datetime.now(UTC),
        )
    )

    evidence = handoff_runtime_evidence(envelope)

    assert envelope.checksum == envelope.expected_checksum()
    assert evidence.metadata["trust"] == "untrusted_handoff_evidence"
    assert evidence.metadata["checksum"] == envelope.checksum
    assert evidence.metadata["handoff_source"] == "checkpoint"
    assert evidence.metadata["handoff_reason"] == HandoffReason.USER_PHASE_BOUNDARY.value
    assert evidence.details == (
        "Completed: contracts merged",
        "Pending: worker gate",
        "Immediate next: run focused tests",
    )
    serialized = envelope.model_dump_json() + repr(evidence)
    assert "reasoning_content" not in serialized
    assert "provider_continuation" not in serialized
    assert "credential" not in serialized
