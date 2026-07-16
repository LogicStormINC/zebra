from __future__ import annotations

from pathlib import Path

from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.session_memory_read import (
    read_session_memory_overdue_archive_recommendations,
    read_session_memory_overdue_closure_decisions,
    read_session_memory_overdue_resolution_checkpoints,
    read_session_memory_overdue_resolution_outcomes,
    read_session_memory_overdue_retention_guidance,
)


def read_memory_resolution_dispatch(
    command: CommandName,
    *,
    database_path: Path,
    session_id: str | None = None,
    approval_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    as_of: str | None = None,
) -> CliCommandResult | None:
    if command == "memory-overdue-resolution-checkpoints":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-resolution-checkpoints",
            payload=read_session_memory_overdue_resolution_checkpoints(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-resolution-outcomes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-resolution-outcomes",
            payload=read_session_memory_overdue_resolution_outcomes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-closure-decisions":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-closure-decisions",
            payload=read_session_memory_overdue_closure_decisions(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-archive-recommendations":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-archive-recommendations",
            payload=read_session_memory_overdue_archive_recommendations(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-guidance":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-guidance",
            payload=read_session_memory_overdue_retention_guidance(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    return None
