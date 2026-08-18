from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from agent_core.contracts import EventPayloadValidationError, validate_event_payload
from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.session_handoff import (
    CompletedToolEvidence,
    EffectIdentity,
    HandoffActorKind,
    HandoffReason,
    HandoffSideEffectClass,
    SessionHandoffEnvelope,
    SessionHandoffValidationContext,
    SessionHandoffValidationError,
    SessionLineage,
    WorkspaceBindingRevision,
    validate_session_handoff,
)
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.session_handoff import (
    SessionHandoffCreateRequest,
    canonical_handoff_request_hash,
)
from pydantic import ValidationError

SOURCE_ID = SessionId(UUID("00000000-0000-0000-0000-000000000001"))
TARGET_ID = SessionId(UUID("00000000-0000-0000-0000-000000000002"))
HANDOFF_ID = HandoffId(UUID("00000000-0000-0000-0000-000000000003"))


def test_canonical_handoff_request_hash_binds_server_derived_identity() -> None:
    request = SessionHandoffCreateRequest(
        source_session_id=SOURCE_ID,
        idempotency_key="retry-key",
        title="Storage stage",
        reason=HandoffReason.OPERATOR_HANDOFF,
        stage_prompt="Implement storage",
        principal_identity_hash="principal-a",
        actor_kind=HandoffActorKind.OPERATOR,
        requested_authority=frozenset({"read", "write"}),
    )

    original = canonical_handoff_request_hash(
        request,
        objective="Continue",
        completed_work=("core",),
        pending_work=("storage",),
    )
    changed = canonical_handoff_request_hash(
        replace(request, principal_identity_hash="principal-b"),
        objective="Continue",
        completed_work=("core",),
        pending_work=("storage",),
    )

    assert len(original) == 64
    assert changed != original


def test_session_lineage_enforces_root_and_linear_child_shape() -> None:
    root = SessionLineage(
        session_id=SOURCE_ID,
        root_session_id=SOURCE_ID,
        stage_index=0,
    )
    child = SessionLineage(
        session_id=TARGET_ID,
        root_session_id=SOURCE_ID,
        parent_session_id=SOURCE_ID,
        inbound_handoff_id=HANDOFF_ID,
        stage_index=1,
    )

    assert root.parent_session_id is None
    assert child.stage_index == 1
    with pytest.raises(ValidationError, match="root lineage"):
        SessionLineage(
            session_id=SOURCE_ID,
            root_session_id=TARGET_ID,
            stage_index=0,
        )
    with pytest.raises(ValidationError, match="identities must be distinct"):
        SessionLineage(
            session_id=TARGET_ID,
            root_session_id=SOURCE_ID,
            parent_session_id=TARGET_ID,
            inbound_handoff_id=HANDOFF_ID,
            stage_index=1,
        )


def test_effectful_evidence_requires_gateway_derived_identity() -> None:
    with pytest.raises(ValidationError, match="requires an effect identity"):
        CompletedToolEvidence(
            tool_call_id="call-1",
            tool_name="files.patch",
            terminal_event_sequence=4,
            terminal_status="succeeded",
            side_effect_class=HandoffSideEffectClass.NON_IDEMPOTENT_EFFECT,
        )

    with pytest.raises(ValidationError, match="read-only"):
        CompletedToolEvidence(
            tool_call_id="call-2",
            tool_name="files.read",
            terminal_event_sequence=5,
            terminal_status="succeeded",
            side_effect_class=HandoffSideEffectClass.READ_ONLY,
            effect_identity=_effect_identity(),
        )


def test_handoff_validator_accepts_safe_transparent_envelope() -> None:
    envelope = _envelope()

    validate_session_handoff(envelope, _validation_context(envelope))


@pytest.mark.parametrize(
    ("context_update", "expected_code"),
    [
        ({"source_status": SessionStatus.RUNNING}, "handoff_source_status_rejected"),
        ({"target_authority": frozenset({"read", "admin"})}, "handoff_authority_widened"),
        ({"effective_depth_limit": 0}, "greater than or equal to 1"),
        ({"effective_depth_limit": 0 + 1}, "handoff_depth_exceeded"),
        ({"parent_has_successor": True}, "handoff_successor_conflict"),
        ({"has_pending_tool": True}, "handoff_source_not_quiescent"),
        ({"terminal_effect_ledger_keys": frozenset()}, "handoff_effect_evidence_unverified"),
    ],
)
def test_handoff_validator_fails_closed(
    context_update: dict[str, object],
    expected_code: str,
) -> None:
    envelope = _envelope(source_stage_index=1)
    context = _validation_context(envelope).model_copy(update=context_update)

    if expected_code == "greater than or equal to 1":
        with pytest.raises(ValidationError, match=expected_code):
            SessionHandoffValidationContext.model_validate(context.model_dump())
        return
    with pytest.raises(SessionHandoffValidationError) as exc_info:
        validate_session_handoff(envelope, context)
    assert expected_code in exc_info.value.codes


def test_handoff_validator_rejects_checksum_and_omitted_constraints() -> None:
    envelope = _envelope().model_copy(update={"checksum": "f" * 64})
    context = _validation_context(envelope).model_copy(
        update={"protected_user_constraints": frozenset({"do not push", "keep evidence"})}
    )

    with pytest.raises(SessionHandoffValidationError) as exc_info:
        validate_session_handoff(envelope, context)

    assert "handoff_checksum_mismatch" in exc_info.value.codes
    assert "handoff_protected_constraints_omitted" in exc_info.value.codes


def test_handoff_events_preserve_legacy_messages_and_require_real_provenance() -> None:
    assert validate_event_payload(EventType.USER_MESSAGE_RECEIVED, {"content": "Continue"}) == {
        "content": "Continue"
    }
    attributed = validate_event_payload(
        EventType.USER_MESSAGE_RECEIVED,
        {
            "content": "Start verification",
            "source": "session_handoff",
            "handoff_id": str(HANDOFF_ID),
            "principal_identity_hash": "principal-sha256",
            "actor_kind": "operator",
            "trust": "operator",
        },
    )
    assert attributed["actor_kind"] == "operator"

    with pytest.raises(EventPayloadValidationError, match="invalid payload"):
        validate_event_payload(
            EventType.USER_MESSAGE_RECEIVED,
            {"content": "Start verification", "source": "session_handoff"},
        )


def test_parent_child_and_workspace_drift_events_have_strict_contracts() -> None:
    parent = validate_event_payload(
        EventType.SESSION_HANDOFF_COMMITTED,
        {
            "handoff_id": str(HANDOFF_ID),
            "target_session_id": str(TARGET_ID),
            "reason": "user_phase_boundary",
            "target_stage_index": 1,
            "source_event_range": {"start_sequence": 0, "end_sequence": 5},
            "source_event_hash": "source-hash",
            "artifact_id": "artifact-1",
            "checksum": "a" * 64,
            "idempotency_key_hash": "key-hash",
        },
    )
    child = validate_event_payload(
        EventType.SESSION_HANDOFF_RECEIVED,
        {
            "parent_session_id": str(SOURCE_ID),
            "root_session_id": str(SOURCE_ID),
            "handoff_id": str(HANDOFF_ID),
            "stage_index": 1,
            "artifact_id": "artifact-1",
            "checksum": "a" * 64,
        },
    )
    assert parent["reason"] == HandoffReason.USER_PHASE_BOUNDARY
    assert child["stage_index"] == 1

    with pytest.raises(EventPayloadValidationError, match="invalid payload"):
        validate_event_payload(
            EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED,
            {
                "handoff_id": str(HANDOFF_ID),
                "expected_revision_hash": "same",
                "actual_revision_hash": "same",
            },
        )


def _envelope(*, source_stage_index: int = 0) -> SessionHandoffEnvelope:
    root_session_id = SOURCE_ID
    evidence = CompletedToolEvidence(
        tool_call_id="call-1",
        tool_name="files.patch",
        terminal_event_sequence=4,
        terminal_status="succeeded",
        side_effect_class=HandoffSideEffectClass.IDEMPOTENT_EFFECT,
        result_artifact_ref="artifact://tool-result",
        effect_identity=_effect_identity(),
    )
    draft = SessionHandoffEnvelope(
        handoff_id=HANDOFF_ID,
        source_session_id=SOURCE_ID,
        target_session_id=TARGET_ID,
        root_session_id=root_session_id,
        source_stage_index=source_stage_index,
        target_stage_index=source_stage_index + 1,
        reason=HandoffReason.USER_PHASE_BOUNDARY,
        objective="Complete the next delivery stage",
        acceptance_criteria=("tests pass",),
        protected_user_constraints=("do not push",),
        completed_work=("core baseline merged",),
        pending_work=("implement storage",),
        immediate_next="Implement storage",
        artifact_refs=("artifact://tool-result",),
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=5),
        source_event_hash="source-hash",
        workspace_revision=_workspace_revision(),
        completed_tool_evidence=(evidence,),
        created_at=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        checksum="0" * 64,
    )
    return draft.model_copy(update={"checksum": draft.expected_checksum()})


def _validation_context(envelope: SessionHandoffEnvelope) -> SessionHandoffValidationContext:
    identity = envelope.completed_tool_evidence[0].effect_identity
    assert identity is not None
    return SessionHandoffValidationContext(
        source_status=SessionStatus.COMPLETED,
        expected_source_session_id=SOURCE_ID,
        expected_target_session_id=TARGET_ID,
        expected_root_session_id=SOURCE_ID,
        expected_source_stage_index=envelope.source_stage_index,
        expected_source_event_range=envelope.source_event_range,
        expected_source_event_hash=envelope.source_event_hash,
        expected_workspace_revision=envelope.workspace_revision,
        protected_user_constraints=frozenset({"do not push"}),
        readable_artifact_refs=frozenset({"artifact://tool-result"}),
        source_authority=frozenset({"read", "write"}),
        target_authority=frozenset({"read"}),
        terminal_effect_ledger_keys=frozenset({identity.ledger_key()}),
        effective_depth_limit=2,
    )


def _effect_identity() -> EffectIdentity:
    return EffectIdentity(
        authority_scope_hash="authority-hash",
        tool_name="files.patch",
        operation_kind="apply_patch",
        target_hash="target-hash",
        canonical_effect_hash="effect-hash",
    )


def _workspace_revision() -> WorkspaceBindingRevision:
    return WorkspaceBindingRevision(
        workspace_id="workspace-1",
        repo_id="zebra-agent",
        revision_hash="workspace-hash",
        commit_sha="abcdef",
    )
