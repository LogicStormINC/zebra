from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from agent_core.application import (
    attachment_refs_from_event,
    current_turn,
    interaction_mode_of,
    project_turns,
)
from agent_core.domain.agent_tasks import (
    ContextLifecycleController,
    ContextLifecycleDecision,
    ContextLifecycleSignals,
    RolloverReason,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.session_handoff import HandoffActorKind
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports import EventStorePort
from agent_security.host_grant import VerifiedHostGrant
from agent_storage import ControlPlaneStores, PostgresControlPlaneStores

from zebra_agent_api.coverage_public_read import coverage_task_read_problem
from zebra_agent_api.coverage_public_summary import coverage_public_summary
from zebra_agent_api.idempotency import replay_idempotent_response, save_idempotent_response
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_handoff import SessionHandoffApi
from zebra_agent_api.session_summary import serialize_session_summary
from zebra_agent_api.task_header import task_header
from zebra_agent_api.task_message_contract import valid_receipt_key
from zebra_agent_api.task_model_usage import summarize_task_model_usage
from zebra_agent_api.task_read_summaries import task_projection_pending, task_summary_fields
from zebra_agent_api.task_responses import is_user_task_event as is_user_task_event
from zebra_agent_api.task_responses import parse_task_limit, task_not_found
from zebra_agent_api.task_responses import serialize_task_event as serialize_task_event
from zebra_agent_api.task_session_api import TaskSessionApi


@dataclass(frozen=True)
class TaskReadApi:
    stores: ControlPlaneStores

    def header(self, task_id: str) -> ApiResponse:
        parsed = parse_task_id(task_id)
        return parsed if isinstance(parsed, ApiResponse) else task_header(self.stores, parsed)

    def get(self, task_id: str) -> ApiResponse:
        parsed = parse_task_id(task_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        cloud = isinstance(self.stores, PostgresControlPlaneStores)
        summary = task_summary_fields(self.stores.tasks, parsed) if cloud else {}
        if isinstance(summary, ApiResponse):
            return summary
        task = self.stores.tasks.get_task(parsed)
        if task is None:
            return task_not_found(task_id)
        if cloud and (
            summary.pop("_summary_active_segment_id") != str(task.active_segment_id)
            or summary["read_summary_through_sequence"] != task.current_sequence
        ):
            return task_projection_pending(parsed, "Task changed while reading its summary")
        session = self.stores.sessions.get_session(task.active_segment_id)
        if session is None:
            return ApiResponse(409, {"task_id": task_id, "status": "projection_incomplete"})
        workspace = self.stores.workspaces.get_workspace(task.active_segment_id)
        body = serialize_session_summary(session, workspace)
        body.update(
            task_id=task_id,
            session_id=task_id,
            current_sequence=task.current_sequence,
            active_segment_sequence=session.current_sequence,
            status=task.status.value,
        )
        body["active_segment_id"] = str(task.active_segment_id)
        body["task_status"] = (
            task.status.value
            if task.status.value in {"completed", "failed", "cancelled"}
            else "open"
        )
        if not cloud:
            _update_turn_fields(body, session, events_store=self.stores.events)
            task_events = self.stores.tasks.read_events(parsed, -1)
            model_usage = summarize_task_model_usage(task_events)
            if model_usage is not None:
                summary["model_usage"] = model_usage
            attachments = [
                ref.to_mapping()
                for item in task_events
                for ref in attachment_refs_from_event(item.event)
            ]
            if attachments:
                summary["attachments"] = attachments
        body.update(summary)
        return ApiResponse(200, coverage_public_summary(self.stores, session.session_id, body))

    def list(self, query: Mapping[str, str]) -> ApiResponse:
        limit = parse_task_limit(query.get("limit"))
        if isinstance(limit, ApiResponse):
            return limit
        store = self.stores.tasks
        projection_store = self.stores.sessions
        workspace_store = self.stores.workspaces
        items: list[dict[str, object]] = []
        for task in store.list_tasks(limit=limit):
            session = projection_store.get_session(task.active_segment_id)
            if session is None:
                continue
            body = serialize_session_summary(
                session,
                workspace_store.get_workspace(task.active_segment_id),
                include_timestamps=True,
            )
            body.update(
                task_id=str(task.task_id),
                session_id=str(task.task_id),
                current_sequence=task.current_sequence,
                status=task.status.value,
                task_status=(
                    task.status.value
                    if task.status
                    in {
                        SessionStatus.COMPLETED,
                        SessionStatus.FAILED,
                        SessionStatus.CANCELLED,
                    }
                    else "open"
                ),
            )
            items.append(coverage_public_summary(self.stores, session.session_id, body))
        return ApiResponse(
            200,
            {"tasks": items, "sessions": items, "count": len(items), "limit": limit},
        )

    def stream(self, task_id: str) -> ApiResponse:
        parsed = parse_task_id(task_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        store = self.stores.tasks
        if store.get_task(parsed) is None:
            return task_not_found(task_id)
        problem = coverage_task_read_problem(self.stores, parsed)
        if problem is not None:
            return problem
        return ApiResponse(
            200,
            {
                "task_id": task_id,
                "session_id": task_id,
                "events": [
                    serialize_task_event(event)
                    for event in store.read_events(parsed, -1)
                    if is_user_task_event(event)
                ],
            },
        )

    def active_segment(self, task_id: str) -> SessionId | ApiResponse:
        parsed = parse_task_id(task_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        active = self.stores.tasks.active_segment(parsed)
        return task_not_found(task_id) if active is None else active

    def internal_segments(self, task_id: str) -> ApiResponse:
        parsed = parse_task_id(task_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        store = self.stores.tasks
        task = store.get_task(parsed)
        if task is None:
            return task_not_found(task_id)
        return ApiResponse(
            200,
            {
                "task_id": task_id,
                "active_segment_id": str(task.active_segment_id),
                "segments": [item.model_dump(mode="json") for item in store.segments(parsed)],
            },
        )


def _update_turn_fields(
    body: dict[str, object],
    session: Session,
    *,
    events_store: EventStorePort,
) -> None:
    """Project the ADR-026 Task/Turn/Segment read fields onto a summary."""

    events = list(events_store.list_for_session(session.session_id))
    terminal = session.status in {
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.CANCELLED,
    }
    body["task_status"] = session.status.value if terminal else "open"
    body["active_segment_id"] = str(session.session_id)
    body["interaction_mode"] = interaction_mode_of(events).value
    records = project_turns(events)
    latest = records[-1] if records else None
    active = current_turn(events)
    visible = active if active is not None else latest
    body["turn_id"] = visible.turn_id if visible is not None else None
    body["current_turn_status"] = visible.status.value if visible is not None else None


def parse_task_id(value: str) -> TaskId | ApiResponse:
    try:
        return TaskId(UUID(value))
    except ValueError:
        return ApiResponse(
            400,
            {
                "task_id": value,
                "status": "invalid_request",
                "reason": "task_id must be a valid UUID",
            },
        )


def create_task(
    app: TaskSessionApi,
    payload: dict[str, object],
    *,
    idempotency_key: str | None,
    host_context: HostContextEnvelope | None = None,
    verified_host_grant: VerifiedHostGrant | None = None,
) -> ApiResponse:
    response = app.create_session(
        payload,
        idempotency_key=idempotency_key,
        host_context=host_context,
        verified_host_grant=verified_host_grant,
    )
    if response.status_code not in {200, 201}:
        return response
    session_id = response.body.get("session_id")
    if not isinstance(session_id, str):
        return ApiResponse(409, {"status": "projection_incomplete"})
    # ponytail: atomic cloud admission already built the index; reuse its header.
    # Missing/legacy indexes still use the existing preparation path.
    task = (
        app.stores.tasks.get_task(TaskId(UUID(session_id)))
        if isinstance(app.stores, PostgresControlPlaneStores) else None
    )
    if task is None:
        task = app.stores.tasks.ensure_for_session(SessionId(UUID(session_id)))
    active = app.stores.sessions.get_session(task.active_segment_id)
    if active is None:
        return ApiResponse(409, {"task_id": str(task.task_id), "status": "projection_incomplete"})
    body = dict(response.body)
    body.update(
        task_id=str(task.task_id),
        session_id=str(task.task_id),
        current_sequence=task.current_sequence,
        active_segment_sequence=active.current_sequence,
    )
    return ApiResponse(response.status_code, body)


def mutate_task(
    app: TaskSessionApi,
    task_id: str,
    action: str,
    payload: dict[str, object],
    *,
    host_context: HostContextEnvelope | None = None,
    idempotency_key: str | None = None,
) -> ApiResponse:
    active = TaskReadApi(app.stores).active_segment(task_id)
    if isinstance(active, ApiResponse):
        return active
    session = app.stores.sessions.get_session(active)
    if action == "resume" and session is not None and session.status is SessionStatus.FAILED:
        rollover = _rollover(
            app.database_path,
            app.stores,
            task_id,
            stage_prompt="Recover from the verified Task checkpoint and continue.",
            objective=f"Recover and continue {session.title}",
            idempotency_key=f"task-recovery:{task_id}:{session.current_sequence}",
            actor_kind=HandoffActorKind.AUTOMATION,
            rollover_reason=RolloverReason.RECOVERY,
        )
        if rollover.status_code not in {200, 201}:
            return rollover
        active = TaskReadApi(app.stores).active_segment(task_id)
        if isinstance(active, ApiResponse):
            return active
    if action == "cancel":
        response = app.cancel_session(
            str(active),
            payload,
            host_context=host_context,
            idempotency_key=idempotency_key,
            task_id=TaskId(UUID(task_id)),
        )
        return _rewrite_task_identity(response, task_id)
    handler = {"suspend": app.suspend_session, "resume": app.resume_session}[action]
    return _rewrite_task_identity(handler(str(active), payload), task_id)


def route_active_task(
    stores: ControlPlaneStores,
    task_id: str,
    handler: Callable[[str], ApiResponse],
) -> ApiResponse:
    active = TaskReadApi(stores).active_segment(task_id)
    if isinstance(active, ApiResponse):
        return active
    return _rewrite_task_identity(handler(str(active)), task_id)


def append_task_message(
    app: TaskSessionApi,
    task_id: str,
    payload: dict[str, object],
    *,
    idempotency_key: str | None,
    message_receipt_version: int = 1,
) -> ApiResponse:
    if message_receipt_version not in {1, 2} or (
        message_receipt_version == 2 and not valid_receipt_key(idempotency_key)
    ):
        return ApiResponse(400, {"status": "invalid_request"})
    action = f"task-message:{task_id}"
    replayed = (
        replay_idempotent_response(
            store=app.stores.idempotency,
            action=action,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if idempotency_key is not None
        else None
    )
    if replayed is not None:
        return replayed

    def finish(response: ApiResponse) -> ApiResponse:
        if idempotency_key is None:
            return response
        return save_idempotent_response(
            store=app.stores.idempotency,
            action=action,
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
        )

    def append(segment: SessionId) -> ApiResponse:
        if message_receipt_version == 2:
            return app.append_session_message(
                str(segment), payload, include_message_coordinates=True
            )
        return app.append_session_message(str(segment), payload)

    reader = TaskReadApi(app.stores)
    active = reader.active_segment(task_id)
    if isinstance(active, ApiResponse):
        return active
    session = app.stores.sessions.get_session(active)
    if session is None:
        return ApiResponse(409, {"task_id": task_id, "status": "projection_incomplete"})
    if session.status not in {
        SessionStatus.COMPLETED,
        SessionStatus.CANCELLED,
        SessionStatus.FAILED,
    }:
        return finish(
            _rewrite_task_identity(append(active), task_id)
        )
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return append(active)
    response = _rollover(
        app.database_path,
        app.stores,
        task_id,
        stage_prompt="Continue from the verified Task checkpoint.",
        objective=content.strip(),
        idempotency_key=idempotency_key
        or _follow_up_key(task_id, session.current_sequence, content),
        actor_kind=HandoffActorKind.AUTOMATION,
        rollover_reason=(
            RolloverReason.TERMINAL_FOLLOW_UP
            if session.status is SessionStatus.COMPLETED
            else RolloverReason.RECOVERY
        ),
    )
    if response.status_code not in {200, 201}:
        return response
    next_active = reader.active_segment(task_id)
    if isinstance(next_active, ApiResponse):
        return finish(next_active)
    appended = _rewrite_task_identity(
        append(next_active), task_id
    )
    if appended.status_code not in {200, 201}:
        return finish(appended)
    return finish(ApiResponse(appended.status_code, {**appended.body, "rolled_over": True}))


def rollover_task(
    app: TaskSessionApi,
    task_id: str,
    payload: dict[str, object],
    *,
    idempotency_key: str | None,
) -> ApiResponse:
    try:
        signals = ContextLifecycleSignals.model_validate(payload.get("signals", {}))
    except ValueError as exc:
        return ApiResponse(
            400, {"task_id": task_id, "status": "invalid_request", "reason": str(exc)}
        )
    decision = ContextLifecycleController().decide(signals)
    if decision is not ContextLifecycleDecision.ROLLOVER:
        return ApiResponse(200, {"task_id": task_id, "decision": decision.value})
    prompt = payload.get("stage_prompt", "Continue from the verified Task checkpoint.")
    objective = payload.get("objective", "Continue the current Task.")
    if not isinstance(prompt, str) or not prompt.strip() or not isinstance(objective, str):
        return ApiResponse(400, {"task_id": task_id, "status": "invalid_request"})
    return _rollover(
        app.database_path,
        app.stores,
        task_id,
        stage_prompt=prompt.strip(),
        objective=objective.strip(),
        idempotency_key=idempotency_key or f"internal-rollover:{task_id}",
        actor_kind=HandoffActorKind.AUTOMATION,
        rollover_reason=(
            RolloverReason.RECOVERY
            if signals.recovery_requires_new_segment
            else RolloverReason.AGENT_HINT
            if signals.agent_rollover_hint
            else RolloverReason.CONTEXT_PRESSURE
        ),
    )


def _rollover(
    database_path: Path,
    stores: ControlPlaneStores,
    task_id: str,
    *,
    stage_prompt: str,
    objective: str,
    idempotency_key: str,
    actor_kind: HandoffActorKind,
    rollover_reason: RolloverReason,
) -> ApiResponse:
    active = TaskReadApi(stores).active_segment(task_id)
    if isinstance(active, ApiResponse):
        return active
    source = stores.sessions.get_session(active)
    if source is None:
        return ApiResponse(409, {"task_id": task_id, "status": "projection_incomplete"})
    return SessionHandoffApi(database_path, stores).create(
        str(active),
        {
            "title": source.title,
            "objective": objective,
            "stage_prompt": stage_prompt,
            "reason": f"internal_{rollover_reason.value}",
        },
        idempotency_key=idempotency_key,
        principal_identity_hash=sha256(f"task:{task_id}".encode()).hexdigest(),
        actor_kind=actor_kind,
    )


def _rewrite_task_identity(response: ApiResponse, task_id: str) -> ApiResponse:
    body = dict(response.body)
    body.update(task_id=task_id, session_id=task_id)
    return ApiResponse(response.status_code, body)


def _follow_up_key(task_id: str, sequence: int, content: str) -> str:
    return "task-follow-up:" + sha256(f"{task_id}:{sequence}:{content}".encode()).hexdigest()
