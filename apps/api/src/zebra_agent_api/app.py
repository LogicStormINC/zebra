from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_core.harness.models import HarnessLoopResult
from agent_integrations import build_model_gateway
from agent_runtime import run_local_harness
from agent_security import PolicyProfile
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_config import ZebraAgentSettings, load_settings


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    body: dict[str, object]


@dataclass(frozen=True)
class ZebraAgentApi:
    database_path: Path
    settings: ZebraAgentSettings

    def health(self) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "status": "ok",
                "service": "zebra-agent-api",
            },
        )

    def get_session(self, session_id: str) -> ApiResponse:
        session = SQLiteProjectionStore(self.database_path).get_session(
            SessionId(UUID(session_id))
        )
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": str(session.session_id),
                "title": session.title,
                "status": session.status.value,
                "current_sequence": session.current_sequence,
            },
        )

    def get_session_stream(self, session_id: str) -> ApiResponse:
        session_key = SessionId(UUID(session_id))
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        events = SQLiteEventStore(self.database_path).list_for_session(session_key)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "events": [
                    {
                        "event_id": str(event.event_id),
                        "sequence": event.sequence,
                        "event_type": event.event_type.value,
                        "actor": event.actor.value,
                        "created_at": event.created_at.isoformat(),
                        "payload": event.payload,
                    }
                    for event in events
                ],
            },
        )

    def create_session(self, payload: dict[str, object]) -> ApiResponse:
        parsed = _parse_create_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed

        if not parsed["execute"]:
            bootstrap = SessionBootstrapService().build(
                SessionBootstrapCommand(
                    title=parsed["title"],
                    user_input=parsed["prompt"],
                    workspace_root=Path(parsed["workspace"]).expanduser().resolve(),
                    policy_profile=parsed["policy_profile"],
                )
            )
            session = bootstrap.session
            event_store = SQLiteEventStore(self.database_path)
            for event in bootstrap.events:
                event_store.append(event)
            SQLiteProjectionStore(self.database_path).save_session(session)
            return ApiResponse(
                status_code=201,
                body={
                    "session_id": str(session.session_id),
                    "title": parsed["title"],
                    "prompt": parsed["prompt"],
                    "workspace": parsed["workspace"],
                    "executed": False,
                    "status": session.status.value,
                },
            )

        result = run_local_harness(
            prompt=parsed["prompt"],
            title=parsed["title"],
            workspace_root=Path(parsed["workspace"]).expanduser().resolve(),
            model_gateway=build_model_gateway(self.settings),
            policy_profile=PolicyProfile(parsed["policy_profile"]),
        )
        event_store = SQLiteEventStore(self.database_path)
        for event in result.events:
            event_store.append(event)
        SQLiteProjectionStore(self.database_path).save_session(result.session)
        trace = _trace_payload(result)
        return ApiResponse(
            status_code=201,
            body={
                "session_id": str(result.session.session_id),
                "title": parsed["title"],
                "prompt": parsed["prompt"],
                "workspace": parsed["workspace"],
                "executed": True,
                "status": result.session.status.value,
                "assistant_message": result.attempt_result.metadata.get("assistant_message"),
                "stop_reason": result.run_result.stop_reason.value,
                "attempts_used": result.run_result.attempts_used,
                "policy_profile": parsed["policy_profile"],
                "trace": trace,
            },
        )


class CreateSessionPayload(TypedDict):
    prompt: str
    title: str
    workspace: str
    execute: bool
    policy_profile: str


def create_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
) -> ZebraAgentApi:
    active_settings = settings or load_settings()
    return ZebraAgentApi(
        database_path=Path(database_path or active_settings.database_url),
        settings=active_settings,
    )


def _parse_create_session_payload(
    payload: dict[str, object],
) -> CreateSessionPayload | ApiResponse:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return _bad_request("prompt must be a non-blank string")

    title = payload.get("title", "Untitled task")
    if not isinstance(title, str) or not title.strip():
        return _bad_request("title must be a non-blank string when provided")

    workspace = payload.get("workspace", ".")
    if not isinstance(workspace, str) or not workspace.strip():
        return _bad_request("workspace must be a non-blank string when provided")

    execute = payload.get("execute", False)
    if not isinstance(execute, bool):
        return _bad_request("execute must be a boolean when provided")

    policy_profile = payload.get("policy_profile", PolicyProfile.WORKSPACE_WRITE.value)
    if not isinstance(policy_profile, str):
        return _bad_request("policy_profile must be a string when provided")
    try:
        PolicyProfile(policy_profile)
    except ValueError:
        return _bad_request("policy_profile is not supported")

    return {
        "prompt": prompt.strip(),
        "title": title.strip(),
        "workspace": workspace.strip(),
        "execute": execute,
        "policy_profile": policy_profile,
    }


def _trace_payload(result: HarnessLoopResult) -> list[dict[str, object]]:
    from agent_core.harness.projection import HarnessTraceProjector

    trace = HarnessTraceProjector().project(result)
    return [
        {
            "attempt_number": attempt.attempt_number,
            "assistant_message": attempt.assistant_message,
            "tools": [
                {
                    "tool_name": tool.tool_name,
                    "status": tool.status,
                    "arguments": tool.arguments,
                    "output": tool.output,
                    "metadata": tool.metadata,
                    "policy_decision": tool.policy_decision,
                }
                for tool in attempt.tools
            ],
        }
        for attempt in trace.attempts
    ]


def _bad_request(reason: str) -> ApiResponse:
    return ApiResponse(
        status_code=400,
        body={
            "status": "invalid_request",
            "reason": reason,
        },
    )
