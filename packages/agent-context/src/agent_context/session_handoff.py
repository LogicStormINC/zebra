from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.context_capsule import ContextCapsule, ContextSourceEventRange
from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.session_handoff import (
    CompletedToolEvidence,
    HandoffReason,
    SessionHandoffEnvelope,
    WorkspaceBindingRevision,
)
from agent_core.ports.context_compiler import RuntimeEvidenceInput


@dataclass(frozen=True, slots=True)
class HandoffEnvelopeBuildInput:
    handoff_id: HandoffId
    source_session_id: SessionId
    target_session_id: SessionId
    root_session_id: SessionId
    source_stage_index: int
    reason: HandoffReason
    objective: str
    immediate_next: str
    source_event_range: ContextSourceEventRange
    source_event_hash: str
    workspace_revision: WorkspaceBindingRevision
    created_at: datetime
    focus: str | None = None
    capsule: ContextCapsule | None = None
    completed_work: tuple[str, ...] = ()
    pending_work: tuple[str, ...] = ()
    completed_tool_evidence: tuple[CompletedToolEvidence, ...] = ()
    known_omissions: tuple[str, ...] = ()


def build_handoff_envelope(request: HandoffEnvelopeBuildInput) -> SessionHandoffEnvelope:
    capsule = request.capsule
    draft = SessionHandoffEnvelope(
        handoff_id=request.handoff_id,
        source_session_id=request.source_session_id,
        target_session_id=request.target_session_id,
        root_session_id=request.root_session_id,
        source_stage_index=request.source_stage_index,
        target_stage_index=request.source_stage_index + 1,
        reason=request.reason,
        focus=request.focus,
        objective=request.objective,
        acceptance_criteria=() if capsule is None else capsule.acceptance_criteria,
        protected_user_constraints=(() if capsule is None else capsule.protected_user_constraints),
        decisions_and_rationale=(
            () if capsule is None else capsule.decisions_and_rationale or capsule.decisions
        ),
        completed_work=request.completed_work,
        pending_work=request.pending_work,
        immediate_next=request.immediate_next,
        touched_files=() if capsule is None else capsule.touched_files,
        validation_results=() if capsule is None else capsule.tests,
        known_failures=() if capsule is None else capsule.errors,
        open_questions=() if capsule is None else capsule.open_questions,
        artifact_refs=() if capsule is None else capsule.artifact_refs,
        source_context_capsule_id=None if capsule is None else capsule.capsule_id,
        source_event_range=request.source_event_range,
        source_event_hash=request.source_event_hash,
        workspace_revision=request.workspace_revision,
        completed_tool_evidence=request.completed_tool_evidence,
        known_omissions=(
            *request.known_omissions,
            *(() if capsule is None else capsule.known_omissions),
        ),
        created_at=request.created_at,
        checksum="0" * 64,
    )
    return draft.model_copy(update={"checksum": draft.expected_checksum()})


def handoff_runtime_evidence(envelope: SessionHandoffEnvelope) -> RuntimeEvidenceInput:
    details = (
        f"Reason: {envelope.reason.value}",
        *((f"Focus: {envelope.focus}",) if envelope.focus else ()),
        *(f"Acceptance: {item}" for item in envelope.acceptance_criteria),
        *(f"Constraint: {item}" for item in envelope.protected_user_constraints),
        *(f"Decision: {item}" for item in envelope.decisions_and_rationale),
        *(f"Completed: {item}" for item in envelope.completed_work),
        *(f"Pending: {item}" for item in envelope.pending_work),
        *(f"Touched file: {item}" for item in envelope.touched_files),
        *(f"Validation: {item}" for item in envelope.validation_results),
        *(f"Known failure: {item}" for item in envelope.known_failures),
        *(f"Open question: {item}" for item in envelope.open_questions),
        *(f"Artifact: {item}" for item in envelope.artifact_refs),
        *(
            "Completed tool: "
            f"{item.tool_name} ({item.tool_call_id}) status={item.terminal_status}"
            + (
                f" artifact={item.result_artifact_ref}"
                if item.result_artifact_ref is not None
                else ""
            )
            for item in envelope.completed_tool_evidence
        ),
        *(f"Known omission: {item}" for item in envelope.known_omissions),
        f"Immediate next: {envelope.immediate_next}",
    )
    return RuntimeEvidenceInput(
        kind="session_handoff",
        summary=envelope.objective,
        details=tuple(details),
        metadata={
            "trust": "untrusted_handoff_evidence",
            "handoff_id": str(envelope.handoff_id),
            "source_session_id": str(envelope.source_session_id),
            "root_session_id": str(envelope.root_session_id),
            "stage_index": envelope.target_stage_index,
            "checksum": envelope.checksum,
            "artifact_refs": list(envelope.artifact_refs),
            "known_omissions": list(envelope.known_omissions),
        },
    )
