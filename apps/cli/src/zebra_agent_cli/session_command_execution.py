from __future__ import annotations

import argparse
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import (
    LeaseConflictError,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api.approval_context import serialize_approval_context
from zebra_agent_api.clarification_context import serialize_clarification_context
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_payloads import parse_resume_session_payload
from zebra_agent_api.task_plan import serialize_task_plan
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryError,
    SessionRecoveryService,
    SessionResumeError,
    SessionResumeService,
    WorkerExecutionError,
)

from zebra_agent_cli.cli_database import (
    _database_path,
)
from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.execution import serialize_trace_events
from zebra_agent_cli.workspace_read import serialize_workspace_projection


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
    approval_context = serialize_approval_context(session.approval_context)
    if approval_context is not None:
        payload["approval_context"] = approval_context
    clarification_context = serialize_clarification_context(session.clarification_context)
    if clarification_context is not None:
        payload["clarification_context"] = clarification_context
    task_plan = serialize_task_plan(session.task_plan)
    if task_plan is not None:
        payload["task_plan"] = task_plan
    return CliCommandResult(command=command, payload=payload)


def _resume_result(
    namespace: argparse.Namespace,
    settings: ZebraAgentSettings,
) -> CliCommandResult:
    database_path = _database_path(namespace.database, settings)
    if not namespace.execute:
        return _session_result("resume", namespace.session_id, database_path)

    parsed = parse_resume_session_payload(
        {
            "worker_id": namespace.worker_id,
            "lease_ttl_seconds": namespace.lease_ttl_seconds,
        }
    )
    if isinstance(parsed, ApiResponse):
        return CliCommandResult(
            command="resume",
            payload={
                **parsed.body,
                "database": str(database_path),
            },
        )

    session_id = SessionId(UUID(namespace.session_id))
    claim_service = SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
        ),
    )
    try:
        result = SessionExecutionService(
            database_path=database_path,
            claim_service=claim_service,
            resume_service=SessionResumeService(claim_service),
            settings=settings,
        ).execute_session(
            session_id,
            worker_id=parsed["worker_id"],
            lease_ttl_seconds=parsed["lease_ttl_seconds"],
        )
    except SessionRecoveryError:
        return CliCommandResult(
            command="resume",
            payload={
                "session_id": namespace.session_id,
                "database": str(database_path),
                "status": "not_found",
            },
        )
    except SessionResumeError:
        return CliCommandResult(
            command="resume",
            payload={
                "session_id": namespace.session_id,
                "database": str(database_path),
                "status": "not_resumable",
                "reason": "cannot_resume_terminal_session",
            },
        )
    except LeaseConflictError:
        return CliCommandResult(
            command="resume",
            payload={
                "session_id": namespace.session_id,
                "database": str(database_path),
                "status": "lease_conflict",
                "reason": "session_already_leased",
            },
        )
    except WorkerExecutionError as error:
        return CliCommandResult(
            command="resume",
            payload={
                "session_id": namespace.session_id,
                "database": str(database_path),
                "status": "execution_error",
                "reason": str(error),
            },
        )
    return CliCommandResult(
        command="resume",
        payload={
            "session_id": namespace.session_id,
            "database": str(database_path),
            "executed": True,
            "worker_id": parsed["worker_id"],
            "status": result.session.status.value,
            "current_sequence": result.session.current_sequence,
            "assistant_message": result.attempt_result.metadata.get("assistant_message"),
            "trace": serialize_trace_events(result.events),
        },
    )
