from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from agent_core.application.approvals import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.sessions import Session
from agent_integrations import build_model_gateway
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_config import ZebraAgentSettings, load_settings

CommandName = Literal["run", "resume", "inspect", "approve", "model"]


@dataclass(frozen=True)
class CliCommandResult:
    command: CommandName
    payload: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(
            {
                "command": self.command,
                **self.payload,
            },
            sort_keys=True,
        )


def execute(
    argv: Sequence[str],
    *,
    settings: ZebraAgentSettings | None = None,
) -> CliCommandResult:
    namespace = _parser().parse_args(list(argv))
    active_settings = settings or load_settings()
    command = namespace.command
    if command == "run":
        return _run_result(namespace, active_settings)
    if command == "resume":
        return _session_result(
            "resume",
            namespace.session_id,
            _database_path(namespace.database, active_settings),
        )
    if command == "inspect":
        return _session_result(
            "inspect",
            namespace.session_id,
            _database_path(namespace.database, active_settings),
        )
    if command == "approve":
        return _approval_result(namespace, _database_path(namespace.database, active_settings))
    if command == "model":
        return _model_result(namespace, active_settings)
    raise ValueError(f"unsupported CLI command: {command}")


def main(argv: Sequence[str] | None = None) -> int:
    result = execute(argv or ())
    print(result.to_json())
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zebra-agent")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="Create a local agent task.")
    run.add_argument("prompt")
    run.add_argument("--title", default="Untitled task")
    run.add_argument("--workspace", default=".")
    run.add_argument("--database")

    resume = subcommands.add_parser("resume", help="Resume a suspended session.")
    resume.add_argument("session_id")
    resume.add_argument("--database")

    inspect = subcommands.add_parser("inspect", help="Inspect a session.")
    inspect.add_argument("session_id")
    inspect.add_argument("--database")

    approve = subcommands.add_parser("approve", help="Record an approval decision.")
    approve.add_argument("session_id")
    approve.add_argument("--decision", choices=("approve", "reject"), required=True)
    approve.add_argument("--reason", default="")
    approve.add_argument("--operator", default="local-operator")
    approve.add_argument("--database")

    model = subcommands.add_parser("model", help="Run one prompt through the configured model.")
    model.add_argument("prompt")

    return parser


def _run_result(
    namespace: argparse.Namespace,
    settings: ZebraAgentSettings,
) -> CliCommandResult:
    session = Session.create(title=namespace.title)
    database_path = _database_path(namespace.database, settings)
    event = SessionEvent.create(
        session_id=session.session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.USER,
        payload={"title": namespace.title},
        created_at=session.created_at,
    )
    SQLiteEventStore(database_path).append(event)
    SQLiteProjectionStore(database_path).save_session(session)
    return CliCommandResult(
        command="run",
        payload={
            "session_id": str(session.session_id),
            "title": namespace.title,
            "prompt": namespace.prompt,
            "workspace": str(Path(namespace.workspace)),
            "database": str(database_path),
            "status": session.status.value,
        },
    )


def _database_path(
    database: str | None,
    settings: ZebraAgentSettings,
) -> Path:
    return Path(database or settings.database_url)


def _session_result(
    command: CommandName,
    session_id: str,
    database_path: Path,
) -> CliCommandResult:
    session = SQLiteProjectionStore(database_path).get_session(SessionId(UUID(session_id)))
    if session is None:
        return CliCommandResult(
            command=command,
            payload={
                "session_id": session_id,
                "database": str(database_path),
                "status": "not_found",
            },
        )
    return CliCommandResult(
        command=command,
        payload={
            "session_id": session_id,
            "database": str(database_path),
            "title": session.title,
            "status": session.status.value,
            "current_sequence": session.current_sequence,
        },
    )


def _approval_result(
    namespace: argparse.Namespace,
    database_path: Path,
) -> CliCommandResult:
    session_id = SessionId(UUID(namespace.session_id))
    projection_store = SQLiteProjectionStore(database_path)
    session = projection_store.get_session(session_id)
    if session is None:
        return CliCommandResult(
            command="approve",
            payload={
                "session_id": namespace.session_id,
                "database": str(database_path),
                "status": "not_found",
            },
        )
    action = (
        ApprovalDecisionAction.GRANT
        if namespace.decision == "approve"
        else ApprovalDecisionAction.REJECT
    )
    reason = namespace.reason or f"{namespace.decision} via CLI"
    try:
        event = ApprovalDecisionService().build_event(
            session=session,
            next_sequence=session.current_sequence + 1,
            command=ApprovalDecisionCommand(
                action=action,
                operator=namespace.operator,
                reason=reason,
            ),
        )
    except ValueError as exc:
        return CliCommandResult(
            command="approve",
            payload={
                "session_id": namespace.session_id,
                "database": str(database_path),
                "status": "invalid_state",
                "reason": str(exc),
            },
        )
    SQLiteEventStore(database_path).append(event)
    updated_session = projection_store.save_session(apply_event(session, event))
    return CliCommandResult(
        command="approve",
        payload={
            "session_id": namespace.session_id,
            "database": str(database_path),
            "decision": namespace.decision,
            "event_type": event.event_type.value,
            "sequence": event.sequence,
            "status": updated_session.status.value,
        },
    )


def _model_result(
    namespace: argparse.Namespace,
    settings: ZebraAgentSettings,
) -> CliCommandResult:
    completion = build_model_gateway(settings).complete(
        [
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content=namespace.prompt,
                created_at=datetime.now(UTC),
            )
        ]
    )
    return CliCommandResult(
        command="model",
        payload={
            "prompt": namespace.prompt,
            "response": completion.assistant_message.content,
            "provider": completion.call_metadata.provider,
            "model_name": completion.call_metadata.model_name,
            "latency_ms": completion.call_metadata.latency_ms,
            "input_tokens": completion.call_metadata.usage.input_tokens,
            "output_tokens": completion.call_metadata.usage.output_tokens,
            "total_tokens": completion.call_metadata.usage.total_tokens,
            "tool_calls": [
                {
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
                for tool_call in completion.tool_calls
            ],
        },
    )
