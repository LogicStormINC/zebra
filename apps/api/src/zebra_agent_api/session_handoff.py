from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from agent_context import HandoffEnvelopeBuildInput, build_handoff_envelope
from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import HandoffId, SessionId, new_handoff_id, new_session_id
from agent_core.domain.session_handoff import (
    HandoffActorKind,
    HandoffOperationStatus,
    HandoffReason,
    SessionHandoffEnvelope,
    SessionHandoffValidationContext,
    SessionHandoffValidationError,
    SessionLineage,
    validate_session_handoff,
)
from agent_core.ports.session_handoff import (
    HandoffOperation,
    SessionHandoffCommitRequest,
    SessionHandoffCreateRequest,
    canonical_handoff_request_hash,
)
from agent_storage import (
    ControlPlaneStores,
    HandoffIdempotencyConflictError,
    HandoffStorageConflictError,
    sqlite_control_plane_stores,
)

from zebra_agent_api.responses import ApiResponse, bad_request, conflict
from zebra_agent_api.session_identity_read import _parse_session_id

_FORBIDDEN_INPUTS = frozenset(
    {
        "actor_kind",
        "authority",
        "checksum",
        "completed_tool_evidence",
        "lineage",
        "root_session_id",
        "target_session_id",
    }
)
_CHECKPOINT_TEXT_LIMIT = 2_000


class _ParsedCreate(TypedDict):
    title: str
    objective: str
    stage_prompt: str
    reason: HandoffReason
    focus: str | None
    completed_work: tuple[str, ...]
    pending_work: tuple[str, ...]


class SessionHandoffApi:
    def __init__(self, database_path: Path, stores: ControlPlaneStores | None = None) -> None:
        active_stores = stores or sqlite_control_plane_stores(database_path)
        self._context_lifecycle = active_stores.context_lifecycle
        self._handoffs = active_stores.handoffs
        self._events = active_stores.events
        self._sessions = active_stores.sessions
        self._effects = active_stores.effects

    def create(
        self,
        source_session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None,
        principal_identity_hash: str,
        actor_kind: HandoffActorKind,
        preview: bool = False,
    ) -> ApiResponse:
        invalid = sorted(_FORBIDDEN_INPUTS.intersection(payload))
        if invalid:
            fields = ", ".join(invalid)
            return bad_request(f"server-derived handoff fields are not accepted: {fields}")
        source_id = _parse_session_id(source_session_id)
        if isinstance(source_id, ApiResponse):
            return source_id
        parsed = _parse_create_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        if not preview and (idempotency_key is None or not idempotency_key.strip()):
            return bad_request("Idempotency-Key is required for handoff creation")
        source = self._sessions.get_session(source_id)
        if source is None:
            return ApiResponse(404, {"session_id": source_session_id, "status": "not_found"})
        now = datetime.now(UTC)
        facts = self._handoffs.inspect_source_facts(source_id, at=now)
        lineage = _source_lineage(self._handoffs.get_lineage(source_id), source_id)
        if lineage.stage_index >= facts.effective_depth_limit:
            return conflict(
                session_id=source_session_id,
                status="handoff_rejected",
                reason="handoff_depth_exceeded",
            )
        target_id = new_session_id()
        handoff_id = new_handoff_id()
        operation: HandoffOperation | None = None
        request = SessionHandoffCreateRequest(
            source_session_id=source_id,
            idempotency_key=idempotency_key or "preview",
            title=parsed["title"],
            reason=parsed["reason"],
            stage_prompt=parsed["stage_prompt"],
            focus=parsed["focus"],
            principal_identity_hash=principal_identity_hash,
            actor_kind=actor_kind,
        )
        request_hash = canonical_handoff_request_hash(
            request,
            objective=parsed["objective"],
            completed_work=parsed["completed_work"],
            pending_work=parsed["pending_work"],
        )
        if not preview:
            try:
                operation = self._handoffs.reserve(
                    request,
                    request_hash=request_hash,
                    expected_source_stream_version=facts.stream_version,
                    source_lease_fence=facts.lease_fence,
                    authority_revision=facts.authority_revision,
                    workspace_revision=facts.workspace_revision,
                    task_profile_revision=facts.task_profile_revision,
                    effective_depth_limit=facts.effective_depth_limit,
                )
            except HandoffIdempotencyConflictError as exc:
                return conflict(
                    session_id=source_session_id,
                    status="handoff_idempotency_conflict",
                    reason=str(exc),
                )
            target_id = operation.target_session_id
            handoff_id = operation.handoff_id
            if operation.status is HandoffOperationStatus.COMMITTED:
                committed = self._handoffs.get_handoff(operation.handoff_id)
                envelope = self._handoffs.get_envelope(operation.handoff_id)
                if committed is None or envelope is None:
                    return conflict(
                        session_id=source_session_id,
                        status="handoff_conflict",
                        reason="committed handoff read model is incomplete",
                    )
                body = _serialize_envelope(envelope, status=committed.child_status)
                body["idempotent_replay"] = True
                return ApiResponse(200, body)
        events = self._events.list_for_session(source_id)
        capsule = self._context_lifecycle.get_active_capsule(source_id)
        completed_work = parsed["completed_work"]
        if actor_kind is HandoffActorKind.AUTOMATION and not completed_work:
            completed_work = _conversation_checkpoint(events)
        envelope = build_handoff_envelope(
            HandoffEnvelopeBuildInput(
                handoff_id=handoff_id,
                source_session_id=source_id,
                target_session_id=target_id,
                root_session_id=lineage.root_session_id,
                source_stage_index=lineage.stage_index,
                reason=request.reason,
                focus=request.focus,
                objective=parsed["objective"],
                completed_work=completed_work,
                pending_work=parsed["pending_work"],
                immediate_next=request.stage_prompt,
                source_event_range=ContextSourceEventRange(
                    start_sequence=0, end_sequence=source.current_sequence
                ),
                source_event_hash=_event_hash(events),
                workspace_revision=facts.workspace_revision,
                created_at=now,
                capsule=None if capsule is None else capsule.capsule,
                known_omissions=(
                    "provider-private continuation, reasoning, credentials and raw tool outputs",
                ),
            )
        )
        validation = SessionHandoffValidationContext(
            source_status=source.status,
            expected_source_session_id=source_id,
            expected_target_session_id=target_id,
            expected_root_session_id=lineage.root_session_id,
            expected_source_stage_index=lineage.stage_index,
            expected_source_event_range=envelope.source_event_range,
            expected_source_event_hash=envelope.source_event_hash,
            expected_workspace_revision=facts.workspace_revision,
            protected_user_constraints=frozenset(envelope.protected_user_constraints),
            readable_artifact_refs=frozenset(envelope.artifact_refs),
            source_authority=frozenset({facts.authority_revision}),
            target_authority=frozenset({facts.authority_revision}),
            terminal_effect_ledger_keys=self._effects.terminal_keys(lineage.root_session_id),
            effective_depth_limit=facts.effective_depth_limit,
            parent_has_successor=any(
                event.event_type is EventType.SESSION_HANDOFF_COMMITTED for event in events
            ),
            has_active_lease=facts.has_active_lease,
            has_pending_tool=bool(capsule and capsule.capsule.pending_tools),
            has_pending_approval=source.status.value == "waiting_approval",
            has_pending_clarification=source.status.value == "waiting_input",
            has_uncertain_effect=self._effects.has_uncertain(lineage.root_session_id),
        )
        try:
            validate_session_handoff(envelope, validation)
        except SessionHandoffValidationError as exc:
            if operation is not None:
                self._handoffs.abort(operation.operation_id, code=exc.codes[0])
            return ApiResponse(
                409,
                {
                    "session_id": source_session_id,
                    "status": "handoff_rejected",
                    "reason": exc.codes[0],
                    "validation_errors": list(exc.codes),
                },
            )
        if preview:
            return ApiResponse(200, _serialize_envelope(envelope, status="preview"))
        assert operation is not None
        try:
            result = self._handoffs.commit(
                SessionHandoffCommitRequest(
                    operation=operation,
                    create_request=request,
                    envelope=envelope,
                    artifact_id=f"handoff-envelope-{handoff_id}",
                )
            )
        except HandoffStorageConflictError as exc:
            return conflict(
                session_id=source_session_id,
                status="handoff_conflict",
                reason=str(exc),
            )
        body = _serialize_envelope(envelope, status=result.child_status)
        body["idempotent_replay"] = result.idempotent_replay
        return ApiResponse(200 if result.idempotent_replay else 201, body)

    def inspect(self, handoff_id: str) -> ApiResponse:
        parsed = _parse_handoff_id(handoff_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        result = self._handoffs.get_handoff(parsed)
        envelope = self._handoffs.get_envelope(parsed)
        if result is None or envelope is None:
            return ApiResponse(404, {"handoff_id": handoff_id, "status": "not_found"})
        body = _serialize_envelope(envelope, status=result.child_status)
        body["idempotent_replay"] = result.idempotent_replay
        return ApiResponse(200, body)

    def lineage(self, session_id: str) -> ApiResponse:
        parsed = _parse_session_id(session_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        lineage = self._handoffs.get_lineage(parsed)
        if not lineage and self._sessions.get_session(parsed) is None:
            return ApiResponse(404, {"session_id": session_id, "status": "not_found"})
        effective = lineage or (_source_lineage((), parsed),)
        return ApiResponse(
            200,
            {
                "session_id": session_id,
                "root_session_id": str(effective[0].root_session_id),
                "stages": [item.model_dump(mode="json") for item in effective],
            },
        )


def _parse_create_payload(payload: dict[str, object]) -> _ParsedCreate | ApiResponse:
    required = ("title", "stage_prompt", "objective")
    if any(
        not isinstance(payload.get(key), str) or not str(payload[key]).strip() for key in required
    ):
        return bad_request("title, stage_prompt and objective must be non-empty strings")
    try:
        reason = HandoffReason(str(payload.get("reason", HandoffReason.USER_PHASE_BOUNDARY)))
    except ValueError:
        return bad_request("unsupported handoff reason")
    focus = payload.get("focus")
    if focus is not None and (not isinstance(focus, str) or not focus.strip()):
        return bad_request("focus must be a non-empty string when provided")
    completed = _string_tuple(payload.get("completed_work", ()), "completed_work")
    pending = _string_tuple(payload.get("pending_work", ()), "pending_work")
    if isinstance(completed, ApiResponse):
        return completed
    if isinstance(pending, ApiResponse):
        return pending
    return {
        "title": str(payload["title"]).strip(),
        "stage_prompt": str(payload["stage_prompt"]).strip(),
        "objective": str(payload["objective"]).strip(),
        "reason": reason,
        "focus": None if focus is None else focus.strip(),
        "completed_work": completed,
        "pending_work": pending,
    }


def _string_tuple(value: object, name: str) -> tuple[str, ...] | ApiResponse:
    if not isinstance(value, list | tuple) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        return bad_request(f"{name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _source_lineage(items: tuple[SessionLineage, ...], source_id: SessionId) -> SessionLineage:
    return next(
        (item for item in items if item.session_id == source_id),
        SessionLineage(session_id=source_id, root_session_id=source_id, stage_index=0),
    )


def _event_hash(events: list[SessionEvent]) -> str:
    return _hash_json([event.model_dump(mode="json") for event in events])


def _conversation_checkpoint(events: list[SessionEvent]) -> tuple[str, ...]:
    prior_user = next(
        (
            event.payload.get("content")
            for event in reversed(events)
            if event.event_type is EventType.USER_MESSAGE_RECEIVED
            and event.payload.get("actor_kind") != HandoffActorKind.AUTOMATION.value
        ),
        None,
    )
    prior_assistant = next(
        (
            event.payload.get("assistant_message")
            for event in reversed(events)
            if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
        ),
        None,
    )
    # ponytail: a two-message tail is enough for immediate follow-ups; long-running
    # work upgrades to the existing Context Capsule compaction path.
    return tuple(
        f"{label}: {_bounded_checkpoint(value)}"
        for label, value in (
            ("Prior user request", prior_user),
            ("Prior assistant response", prior_assistant),
        )
        if isinstance(value, str) and value.strip()
    )


def _bounded_checkpoint(value: str) -> str:
    compact = value.strip()
    if len(compact) <= _CHECKPOINT_TEXT_LIMIT:
        return compact
    return f"{compact[: _CHECKPOINT_TEXT_LIMIT - 1].rstrip()}…"


def _hash_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _parse_handoff_id(value: str) -> HandoffId | ApiResponse:
    try:
        from uuid import UUID

        return HandoffId(UUID(value))
    except ValueError:
        return bad_request("handoff_id must be a valid UUID")


def _serialize_envelope(envelope: SessionHandoffEnvelope, *, status: str) -> dict[str, object]:
    return {
        "handoff_id": str(envelope.handoff_id),
        "source_session_id": str(envelope.source_session_id),
        "child_session_id": str(envelope.target_session_id),
        "root_session_id": str(envelope.root_session_id),
        "stage_index": envelope.target_stage_index,
        "status": status,
        "checksum": envelope.checksum,
        "envelope": envelope.model_dump(mode="json"),
    }
