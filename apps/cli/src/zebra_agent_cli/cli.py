from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.approvals import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_integrations import build_model_gateway
from agent_security import PolicyProfile
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_config import ZebraAgentSettings, load_settings
from zebra_agent_worker import (
    SessionClaimService,
    SessionControlError,
    SessionControlService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeService,
)

from zebra_agent_cli.artifact_read import (
    prune_artifact,
    read_artifact_content,
    read_artifact_detail,
)
from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.execution import (
    execute_durable_run,
    serialize_run_execution,
    serialize_trace_events,
)
from zebra_agent_cli.read_commands import add_read_subparsers, read_command_result
from zebra_agent_cli.session_commit_write import commit_session
from zebra_agent_cli.workspace_read import serialize_workspace_projection


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
        return _resume_result(namespace, active_settings)
    if command == "suspend":
        return _suspend_result(namespace, active_settings)
    if command == "inspect":
        return _session_result(
            "inspect",
            namespace.session_id,
            _database_path(namespace.database, active_settings),
        )
    if command == "approve":
        return _approval_result(namespace, _database_path(namespace.database, active_settings))
    if command == "artifact":
        return _artifact_result(namespace, _database_path(namespace.database, active_settings))
    if command in {"diff", "stream", "delivery-audit"}:
        return read_command_result(
            command,
            session_id=namespace.session_id,
            database_path=_database_path(namespace.database, active_settings),
        )
    if command == "commit":
        return CliCommandResult(
            command="commit",
            payload=commit_session(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
                message=namespace.message,
                author_name=namespace.author_name,
                author_email=namespace.author_email,
                idempotency_key=namespace.idempotency_key,
            ),
        )
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
    run.add_argument("--execute", action="store_true")
    run.add_argument(
        "--policy-profile",
        choices=tuple(profile.value for profile in PolicyProfile),
        default=PolicyProfile.WORKSPACE_WRITE.value,
    )

    resume = subcommands.add_parser("resume", help="Resume a suspended session.")
    resume.add_argument("session_id")
    resume.add_argument("--database")
    resume.add_argument("--execute", action="store_true")
    resume.add_argument("--worker-id", default="local-worker")
    resume.add_argument("--lease-ttl-seconds", type=int, default=30)

    suspend = subcommands.add_parser("suspend", help="Suspend a local session.")
    suspend.add_argument("session_id")
    suspend.add_argument("--database")

    inspect = subcommands.add_parser("inspect", help="Inspect a session.")
    inspect.add_argument("session_id")
    inspect.add_argument("--database")

    add_read_subparsers(subcommands)

    commit = subcommands.add_parser("commit", help="Create one local commit for a session.")
    commit.add_argument("session_id")
    commit.add_argument("--message", required=True)
    commit.add_argument("--author-name", default="Zebra Agent")
    commit.add_argument("--author-email", default="zebra-agent@example.local")
    commit.add_argument("--idempotency-key")
    commit.add_argument("--database")

    artifact = subcommands.add_parser("artifact", help="Inspect or read session artifacts.")
    artifact_subcommands = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_inspect = artifact_subcommands.add_parser(
        "inspect",
        help="Inspect one session artifact.",
    )
    artifact_inspect.add_argument("session_id")
    artifact_inspect.add_argument("artifact_id")
    artifact_inspect.add_argument("--database")
    artifact_read = artifact_subcommands.add_parser(
        "read",
        help="Read one payload-backed session artifact.",
    )
    artifact_read.add_argument("session_id")
    artifact_read.add_argument("artifact_id")
    artifact_read.add_argument("--database")
    artifact_prune = artifact_subcommands.add_parser(
        "prune",
        help="Prune one managed payload-backed session artifact.",
    )
    artifact_prune.add_argument("session_id")
    artifact_prune.add_argument("artifact_id")
    artifact_prune.add_argument("--database")

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
    database_path = _database_path(namespace.database, settings)
    workspace = Path(namespace.workspace)
    if namespace.execute:
        execution_result = execute_durable_run(
            prompt=namespace.prompt,
            title=namespace.title,
            workspace_root=workspace.expanduser().resolve(),
            database_path=database_path,
            settings=settings,
            policy_profile=PolicyProfile(namespace.policy_profile),
        )
        session = execution_result.harness_result.session
        payload = serialize_run_execution(execution_result)
    else:
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title=namespace.title,
                user_input=namespace.prompt,
                workspace_root=workspace.expanduser().resolve(),
                policy_profile=namespace.policy_profile,
            )
        )
        session = bootstrap.session
        event_store = SQLiteEventStore(database_path)
        for event in bootstrap.events:
            event_store.append(event)
        SQLiteProjectionStore(database_path).save_session(session)
        payload = {
            "executed": False,
            "status": session.status.value,
        }
    return CliCommandResult(
        command="run",
        payload={
            "session_id": str(session.session_id),
            "title": namespace.title,
            "prompt": namespace.prompt,
            "workspace": str(workspace),
            "database": str(database_path),
            **payload,
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
    session_key = SessionId(UUID(session_id))
    session = SQLiteProjectionStore(database_path).get_session(session_key)
    if session is None:
        return CliCommandResult(
            command=command,
            payload={
                "session_id": session_id,
                "database": str(database_path),
                "status": "not_found",
            },
        )
    payload: dict[str, object] = {
        "session_id": session_id,
        "database": str(database_path),
        "title": session.title,
        "status": session.status.value,
        "current_sequence": session.current_sequence,
    }
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_key)
    serialized_workspace = serialize_workspace_projection(workspace)
    if serialized_workspace is not None:
        payload["workspace"] = serialized_workspace
    return CliCommandResult(command=command, payload=payload)


def _resume_result(
    namespace: argparse.Namespace,
    settings: ZebraAgentSettings,
) -> CliCommandResult:
    database_path = _database_path(namespace.database, settings)
    if not namespace.execute:
        return _session_result("resume", namespace.session_id, database_path)

    session_id = SessionId(UUID(namespace.session_id))
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
        ),
    )
    result = SessionExecutionService(
        database_path=database_path,
        claim_service=claim_service,
        resume_service=SessionResumeService(claim_service),
        settings=settings,
    ).execute_session(
        session_id,
        worker_id=namespace.worker_id,
        lease_ttl_seconds=namespace.lease_ttl_seconds,
    )
    return CliCommandResult(
        command="resume",
        payload={
            "session_id": namespace.session_id,
            "database": str(database_path),
            "executed": True,
            "worker_id": namespace.worker_id,
            "status": result.session.status.value,
            "current_sequence": result.session.current_sequence,
            "assistant_message": result.attempt_result.metadata.get("assistant_message"),
            "trace": serialize_trace_events(result.events),
        },
    )


def _suspend_result(
    namespace: argparse.Namespace,
    settings: ZebraAgentSettings,
) -> CliCommandResult:
    database_path = _database_path(namespace.database, settings)
    try:
        result = SessionControlService(database_path).suspend_session(
            SessionId(UUID(namespace.session_id))
        )
    except SessionControlError as error:
        return CliCommandResult(
            command="suspend",
            payload={
                "session_id": namespace.session_id,
                "database": str(database_path),
                "status": "not_suspendable",
                "reason": str(error),
            },
        )
    return CliCommandResult(
        command="suspend",
        payload={
            "session_id": namespace.session_id,
            "database": str(database_path),
            "suspended": True,
            "status": "suspended",
            "workspace_status": result.workspace.status.value,
            "snapshot_id": result.workspace.snapshot_id,
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


def _artifact_result(
    namespace: argparse.Namespace,
    database_path: Path,
) -> CliCommandResult:
    if namespace.artifact_command == "inspect":
        payload = read_artifact_detail(
            database_path=database_path,
            session_id=namespace.session_id,
            artifact_id=namespace.artifact_id,
        )
        return CliCommandResult(command="artifact", payload=payload)
    if namespace.artifact_command == "read":
        payload = read_artifact_content(
            database_path=database_path,
            session_id=namespace.session_id,
            artifact_id=namespace.artifact_id,
        )
        return CliCommandResult(command="artifact", payload=payload)
    if namespace.artifact_command == "prune":
        payload = prune_artifact(
            database_path=database_path,
            session_id=namespace.session_id,
            artifact_id=namespace.artifact_id,
        )
        return CliCommandResult(command="artifact", payload=payload)
    raise ValueError(f"unsupported artifact command: {namespace.artifact_command}")
