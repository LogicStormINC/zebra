from datetime import UTC, datetime

from agent_context import (
    HandoffEnvelopeBuildInput,
    build_handoff_envelope,
    handoff_runtime_evidence,
)
from agent_core.domain.context_capsule import ContextCapsule, ContextSourceEventRange
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
    serialized = envelope.model_dump_json() + repr(evidence)
    assert "reasoning_content" not in serialized
    assert "provider_continuation" not in serialized
    assert "credential" not in serialized


def test_handoff_runtime_evidence_exposes_every_continuity_field() -> None:
    source = new_session_id()
    target = new_session_id()
    capsule = ContextCapsule(
        capsule_id="capsule-rich",
        objective="Continue the Cloud integration.",
        acceptance_criteria=("Trench read E2E passes",),
        protected_user_constraints=("Do not write business data",),
        decisions_and_rationale=("Use the signed Host boundary",),
        touched_files=("apps/worker/context.py",),
        tests=("pytest tests/worker passed",),
        errors=("Host timeout remains",),
        artifact_refs=("artifact://handoff/evidence",),
        open_questions=("Which Trench endpoint is authoritative?",),
        immediate_next="Run the real boundary E2E.",
        source_hash="a" * 64,
        confidence=1.0,
        known_omissions=("provider private continuation",),
        created_at=datetime.now(UTC),
    )
    envelope = build_handoff_envelope(
        HandoffEnvelopeBuildInput(
            handoff_id=new_handoff_id(),
            source_session_id=source,
            target_session_id=target,
            root_session_id=source,
            source_stage_index=0,
            reason=HandoffReason.USER_PHASE_BOUNDARY,
            objective=capsule.objective,
            completed_work=("Cloud Worker wired",),
            pending_work=("Trench acceptance",),
            immediate_next=capsule.immediate_next,
            source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=10),
            source_event_hash="event-hash",
            workspace_revision=WorkspaceBindingRevision(
                workspace_id="/repo", revision_hash="workspace-hash"
            ),
            created_at=datetime.now(UTC),
            capsule=capsule,
        )
    )

    evidence = handoff_runtime_evidence(envelope)
    rendered = "\n".join(evidence.details)

    for marker in (
        "Acceptance: Trench read E2E passes",
        "Touched file: apps/worker/context.py",
        "Validation: pytest tests/worker passed",
        "Known failure: Host timeout remains",
        "Open question: Which Trench endpoint is authoritative?",
        "Artifact: artifact://handoff/evidence",
        "Known omission: provider private continuation",
    ):
        assert marker in rendered
