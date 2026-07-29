from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import UUID

from agent_core.application import attachment_refs_from_event
from agent_core.domain.agent_tasks import (
    ContextLifecycleController,
    ContextLifecycleDecision,
    ContextLifecycleSignals,
    RolloverReason,
)
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId, new_task_id
from agent_core.domain.session_handoff import HandoffActorKind
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.agent_tasks import TaskEvent
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)

from zebra_agent_api.idempotency import replay_idempotent_response, save_idempotent_response
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_handoff import SessionHandoffApi
from zebra_agent_api.session_summary import serialize_session_summary

DEFAULT_TASK_LIMIT = 50
MAX_TASK_LIMIT = 100
class TaskSessionApi(Protocol):
    @property
    def database_path(self) -> Path: ...

    def create_session(
        self,
        payload: dict[str, object],
        *,
        idempotency_key: str | None = None,
        session_id: SessionId | None = None,
    ) -> ApiResponse: ...

    def append_session_message(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        task_id: str | None = None,
    ) -> ApiResponse: ...

    def cancel_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse: ...

    def suspend_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse: ...

    def resume_session(self, session_id: str, payload: dict[str, object]) -> ApiResponse: ...


@dataclass(frozen=True)
class TaskReadApi:
    database_path: Path

    def get(self, task_id: str) -> ApiResponse:
        parsed = parse_task_id(task_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        task = SQLiteAgentTaskStore(self.database_path).get_task(parsed)
        if task is None:
            return _not_found(task_id)
        session = SQLiteProjectionStore(self.database_path).get_session(task.active_segment_id)
        if session is None:
            return ApiResponse(409, {"task_id": task_id, "status": "projection_incomplete"})
        workspace = SQLiteWorkspaceProjectionStore(self.database_path).get_workspace(
            task.active_segment_id
        )
        body = serialize_session_summary(session, workspace)
        _hide_workspace_paths(body)
        body.update(
            task_id=task_id,
            session_id=task_id,
            current_sequence=task.current_sequence,
            status=task.status.value,
        )
        events = [
            item.event for item in SQLiteAgentTaskStore(self.database_path).read_events(parsed, -1)
        ]
        attachments = [
            ref.to_mapping() for event in events for ref in attachment_refs_from_event(event)
        ]
        if attachments:
            body["attachments"] = attachments
        return ApiResponse(200, body)

    def list(
        self,
        query: Mapping[str, str],
        *,
        hide_workspace_paths: bool = False,
    ) -> ApiResponse:
        limit = _parse_limit(query.get("limit"))
        if isinstance(limit, ApiResponse):
            return limit
        store = SQLiteAgentTaskStore(self.database_path)
        projection_store = SQLiteProjectionStore(self.database_path)
        workspace_store = SQLiteWorkspaceProjectionStore(self.database_path)
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
            if hide_workspace_paths:
                _hide_workspace_paths(body)
            body.update(
                task_id=str(task.task_id),
                session_id=str(task.task_id),
                current_sequence=task.current_sequence,
                status=task.status.value,
            )
            items.append(body)
        return ApiResponse(
            200,
            {"tasks": items, "sessions": items, "count": len(items), "limit": limit},
        )

    def stream(self, task_id: str) -> ApiResponse:
        parsed = parse_task_id(task_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        store = SQLiteAgentTaskStore(self.database_path)
        if store.get_task(parsed) is None:
            return _not_found(task_id)
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
        active = SQLiteAgentTaskStore(self.database_path).active_segment(parsed)
        return _not_found(task_id) if active is None else active

    def internal_segments(self, task_id: str) -> ApiResponse:
        parsed = parse_task_id(task_id)
        if isinstance(parsed, ApiResponse):
            return parsed
        store = SQLiteAgentTaskStore(self.database_path)
        task = store.get_task(parsed)
        if task is None:
            return _not_found(task_id)
        return ApiResponse(
            200,
            {
                "task_id": task_id,
                "active_segment_id": str(task.active_segment_id),
                "segments": [item.model_dump(mode="json") for item in store.segments(parsed)],
            },
        )


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
) -> ApiResponse:
    if "finos_journal_provider" in payload:
        return ApiResponse(
            400,
            {
                "status": "invalid_request",
                "reason": "FinOS Journal provider must be bound after Task creation",
            },
        )
    task_id = new_task_id()
    response = app.create_session(
        payload,
        idempotency_key=idempotency_key,
        session_id=SessionId(task_id),
    )
    if response.status_code not in {200, 201}:
        return response
    session_id = response.body.get("session_id")
    if not isinstance(session_id, str):
        return ApiResponse(409, {"status": "projection_incomplete"})
    task = SQLiteAgentTaskStore(app.database_path).ensure_for_session(SessionId(UUID(session_id)))
    body = dict(response.body)
    body.pop("workspace", None)
    body.update(task_id=str(task.task_id), session_id=str(task.task_id))
    return ApiResponse(response.status_code, body)


def mutate_task(
    app: TaskSessionApi,
    task_id: str,
    action: str,
    payload: dict[str, object],
) -> ApiResponse:
    reader = TaskReadApi(app.database_path)
    active = reader.active_segment(task_id)
    if isinstance(active, ApiResponse):
        return active
    session = SQLiteProjectionStore(app.database_path).get_session(active)
    if action == "resume" and session is not None and session.status is SessionStatus.FAILED:
        rollover = _rollover(
            app.database_path,
            task_id,
            stage_prompt="Recover from the verified Task checkpoint and continue.",
            objective=f"Recover and continue {session.title}",
            idempotency_key=f"task-recovery:{task_id}:{session.current_sequence}",
            actor_kind=HandoffActorKind.AUTOMATION,
            rollover_reason=RolloverReason.RECOVERY,
        )
        if rollover.status_code not in {200, 201}:
            return rollover
        active = reader.active_segment(task_id)
        if isinstance(active, ApiResponse):
            return active
    handler = {
        "cancel": app.cancel_session,
        "suspend": app.suspend_session,
        "resume": app.resume_session,
    }[action]
    return _rewrite_task_identity(handler(str(active), payload), task_id)


def route_active_task(
    database_path: Path,
    task_id: str,
    handler: Callable[[str], ApiResponse],
) -> ApiResponse:
    active = TaskReadApi(database_path).active_segment(task_id)
    if isinstance(active, ApiResponse):
        return active
    return _rewrite_task_identity(handler(str(active)), task_id)


def append_task_message(
    app: TaskSessionApi,
    task_id: str,
    payload: dict[str, object],
    *,
    idempotency_key: str | None,
) -> ApiResponse:
    action = f"task-message:{task_id}"
    replayed = replay_idempotent_response(
        database_path=app.database_path,
        action=action,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replayed is not None:
        return replayed

    def finish(response: ApiResponse) -> ApiResponse:
        if idempotency_key is None:
            return response
        return save_idempotent_response(
            database_path=app.database_path,
            action=action,
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
        )

    reader = TaskReadApi(app.database_path)
    active = reader.active_segment(task_id)
    if isinstance(active, ApiResponse):
        return active
    session = SQLiteProjectionStore(app.database_path).get_session(active)
    if session is None:
        return ApiResponse(409, {"task_id": task_id, "status": "projection_incomplete"})
    if session.status not in {
        SessionStatus.COMPLETED,
        SessionStatus.CANCELLED,
        SessionStatus.FAILED,
    }:
        return finish(
            _rewrite_task_identity(
                app.append_session_message(str(active), payload, task_id=task_id), task_id
            )
        )
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return app.append_session_message(str(active), payload, task_id=task_id)
    response = _rollover(
        app.database_path,
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
        app.append_session_message(str(next_active), payload, task_id=task_id), task_id
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


def serialize_task_event(item: TaskEvent) -> dict[str, object]:
    event = item.event
    payload = dict(event.payload)
    if (
        event.event_type is EventType.USER_MESSAGE_RECEIVED
        and payload.get("source") == "session_handoff"
    ):
        payload = {"content": payload.get("content", "")}
    elif event.event_type is EventType.TASK_PREPARED:
        payload.pop("workspace_root", None)
    return {
        "event_id": str(event.event_id),
        "sequence": item.task_sequence,
        "event_type": event.event_type.value,
        "actor": event.actor.value,
        "created_at": event.created_at.isoformat(),
        "payload": payload,
    }


def is_user_task_event(item: TaskEvent) -> bool:
    event = item.event
    if event.event_type in {
        EventType.SESSION_HANDOFF_COMMITTED,
        EventType.SESSION_HANDOFF_RECEIVED,
    }:
        return False
    if item.segment_id != TaskId(item.task_id) and event.event_type in {
        EventType.SESSION_CREATED,
        EventType.TASK_PREPARED,
    }:
        return False
    if event.event_type is EventType.USER_MESSAGE_RECEIVED:
        return event.payload.get("actor_kind") != HandoffActorKind.AUTOMATION.value
    return True


def _rollover(
    database_path: Path,
    task_id: str,
    *,
    stage_prompt: str,
    objective: str,
    idempotency_key: str,
    actor_kind: HandoffActorKind,
    rollover_reason: RolloverReason,
) -> ApiResponse:
    active = TaskReadApi(database_path).active_segment(task_id)
    if isinstance(active, ApiResponse):
        return active
    source = SQLiteProjectionStore(database_path).get_session(active)
    if source is None:
        return ApiResponse(409, {"task_id": task_id, "status": "projection_incomplete"})
    return SessionHandoffApi(database_path).create(
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
    body.pop("workspace", None)
    body.update(task_id=task_id, session_id=task_id)
    return ApiResponse(response.status_code, body)


def _hide_workspace_paths(body: dict[str, object]) -> None:
    workspace = body.get("workspace")
    if not isinstance(workspace, dict):
        return
    workspace.pop("workspace_root", None)
    snapshot = workspace.get("snapshot")
    if isinstance(snapshot, dict):
        snapshot.pop("snapshot_path", None)


def _follow_up_key(task_id: str, sequence: int, content: str) -> str:
    return "task-follow-up:" + sha256(f"{task_id}:{sequence}:{content}".encode()).hexdigest()


def _parse_limit(raw: str | None) -> int | ApiResponse:
    try:
        limit = DEFAULT_TASK_LIMIT if raw is None else int(raw)
    except ValueError:
        limit = 0
    if 1 <= limit <= MAX_TASK_LIMIT:
        return limit
    return ApiResponse(
        400,
        {"status": "invalid_request", "reason": "limit must be an integer between 1 and 100"},
    )


def _not_found(task_id: str) -> ApiResponse:
    return ApiResponse(404, {"task_id": task_id, "status": "not_found"})
