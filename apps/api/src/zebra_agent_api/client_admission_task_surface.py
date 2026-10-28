"""Ready UI, sanitized input and the first RUN become visible in one native commit."""

from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from ag_ui.core import UserMessage
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId

from zebra_agent_api.ag_ui_command import _admit_client_mounts
from zebra_agent_api.client_admission_atomic import eligible_atomic_surface
from zebra_agent_api.client_admission_task import prepare_atomic_task, validate_atomic_task
from zebra_agent_api.client_surface import open_client_surface
from zebra_agent_api.responses import ApiResponse


def validate_initial_surface(app: Any, body: Any) -> None:
    payload = body.payload
    if set(payload) != {"task", "surface", "input"} or any(
        not isinstance(payload[k], dict) for k in payload
    ):
        raise ValueError("exact Task, Surface and initial input required")
    validate_atomic_task(
        app, body.model_copy(update={"payload": payload["task"]}), initial_run=True
    )
    if not eligible_atomic_surface(app):
        raise ValueError("initial UI requires exact same PG ports")
    if set(payload["input"]) not in ({"state"}, {"state", "message"}) or not isinstance(
        payload["input"]["state"], dict
    ):
        raise ValueError("initial input only accepts client Readable state")
    if "message" in payload["input"]:
        message = payload["input"]["message"]
        prompt = payload["task"].get("prompt")
        if (
            not isinstance(message, dict)
            or set(message) != {"id", "role", "content"}
            or not isinstance(prompt, str)
            or message.get("content") != prompt.strip()
        ):
            raise ValueError("captured initial user message must match the Task prompt")
        UserMessage.model_validate(message)
        from agent_core.domain.client_context import validate_client_state_json

        validate_client_state_json({"message": message})
    # All state validation runs again against the current native mounted Profile.
    from agent_core.domain.client_context import validate_client_state_json

    validate_client_state_json(payload["input"]["state"])
    surface = payload["surface"]
    if surface.get("controller") is not True or not isinstance(surface.get("mount"), dict):
        raise ValueError("explicit initial Controller mount required")


def prepare_initial_surface(
    app: Any, request: Any, body: Any, scoped: str
) -> Callable[[], ApiResponse] | None:
    validate_initial_surface(app, body)
    create = prepare_atomic_task(
        app,
        request,
        body.model_copy(update={"payload": body.payload["task"]}),
        scoped,
        initial_run=True,
        defer_initial_run=True,
    )
    if create is None:
        return None

    def admit() -> ApiResponse:
        response = create()
        if response.status_code != 201:
            return response
        task = str(response.body["task_id"])
        surface = open_client_surface(
            app,
            replace(
                request,
                path=f"/v1/tasks/{task}/runs/{body.run}/client-surface",
                body=body.payload["surface"],
            ),
        )
        if surface.status_code != 201:
            return surface
        metadata = surface.body
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"x-zebra-client-session", "x-zebra-client-fence"}
        }
        headers.update(
            {
                "X-Zebra-Client-Session": metadata["session_credential"],
                "X-Zebra-Client-Fence": metadata["controller_fence_token"],
            }
        )
        mount = body.payload["surface"]["mount"]
        client = {
            "thread_id": task,
            "run_id": body.run,
            "input": {
                **(
                    {"threadId": task, "runId": body.run, "protocolVersion": "1.0", "context": []}
                    if "message" in body.payload["input"]
                    else {}
                ),
                "messages": [body.payload["input"]["message"]]
                if "message" in body.payload["input"]
                else [],
                "tools": [],
                "state": body.payload["input"]["state"],
                "forwardedProps": {
                    "clientStateVersion": 1,
                    "frontendAppId": mount["frontend_app_id"],
                    "clientSessionId": metadata["client_session_id"],
                    "uiRevision": metadata["ui_revision"],
                    "profileDigest": metadata["profile_digest"],
                    "mountedSnapshotDigest": metadata["mounted_snapshot_digest"],
                    "clientBindingDigest": metadata["binding_digest"],
                },
            },
        }
        denied = _admit_client_mounts(
            app, client, request.path, request=replace(request, headers=headers)
        )
        if denied is not None:
            return denied
        session = SessionId(UUID(task))
        revision = cast(int, response.body["current_sequence"])
        command = SessionCommand(
            session_id=session,
            kind=SessionCommandKind.RUN,
            expected_revision=revision,
            idempotency_key="initial-ui-run:" + scoped,
            payload=client,
        )
        event = SessionEvent.create(
            session_id=session,
            sequence=revision + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
            idempotency_key=command.idempotency_key,
        )
        # No execution or queue publication here. Existing event append enlists
        # the native wakeup/outbox in the same outer transaction and commit fence.
        app.stores.events.append(event)
        response.body.update(
            run_id=body.run,
            current_sequence=revision + 1,
            status="queued",
            executed=False,
            command={
                "command_id": str(command.command_id),
                "status": "accepted",
                **(
                    {
                        "event_id": str(event.event_id),
                        "segment_id": str(session),
                        "event_sequence": event.sequence,
                        "idempotency_key": command.idempotency_key,
                    }
                    if "message" in body.payload["input"]
                    else {}
                ),
            },
            surface=metadata,
        )
        return response

    return admit
