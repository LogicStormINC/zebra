from __future__ import annotations

from pathlib import Path

from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.session_memory_read import (
    read_session_memory_backlog_aging_signals,
    read_session_memory_backlog_pressure_signals,
    read_session_memory_governance_signals,
    read_session_memory_operations_overview,
    read_session_memory_queue,
    read_session_memory_queue_summary,
    read_session_memory_review_velocity_signals,
    read_tenant_memory,
    read_tenant_memory_queue,
    read_tenant_memory_queue_summary,
    read_user_memory,
    read_user_memory_queue,
    read_user_memory_queue_summary,
)


def read_memory_governance_dispatch(
    command: CommandName,
    *,
    database_path: Path,
    session_id: str | None = None,
    approval_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    as_of: str | None = None,
) -> CliCommandResult | None:
    if command == "memory-aging":
        assert session_id is not None
        return CliCommandResult(
            command="memory-aging",
            payload=read_session_memory_backlog_aging_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-governance":
        assert session_id is not None
        return CliCommandResult(
            command="memory-governance",
            payload=read_session_memory_governance_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
            ),
        )

    if command == "memory-velocity":
        assert session_id is not None
        return CliCommandResult(
            command="memory-velocity",
            payload=read_session_memory_review_velocity_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-pressure":
        assert session_id is not None
        return CliCommandResult(
            command="memory-pressure",
            payload=read_session_memory_backlog_pressure_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overview":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overview",
            payload=read_session_memory_operations_overview(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
            ),
        )

    if command == "memory-queue":
        assert session_id is not None
        return CliCommandResult(
            command="memory-queue",
            payload=read_session_memory_queue(
                database_path=database_path,
                session_id=session_id,
            ),
        )

    if command == "memory-queue-summary":
        assert session_id is not None
        return CliCommandResult(
            command="memory-queue-summary",
            payload=read_session_memory_queue_summary(
                database_path=database_path,
                session_id=session_id,
            ),
        )

    if command == "memory-user":
        assert user_id is not None
        return CliCommandResult(
            command="memory-user",
            payload=read_user_memory(
                database_path=database_path,
                user_id=user_id,
            ),
        )

    if command == "memory-user-queue":
        assert user_id is not None
        return CliCommandResult(
            command="memory-user-queue",
            payload=read_user_memory_queue(
                database_path=database_path,
                user_id=user_id,
            ),
        )

    if command == "memory-user-queue-summary":
        assert user_id is not None
        return CliCommandResult(
            command="memory-user-queue-summary",
            payload=read_user_memory_queue_summary(
                database_path=database_path,
                user_id=user_id,
            ),
        )

    if command == "memory-tenant":
        assert tenant_id is not None
        return CliCommandResult(
            command="memory-tenant",
            payload=read_tenant_memory(
                database_path=database_path,
                tenant_id=tenant_id,
            ),
        )

    if command == "memory-tenant-queue":
        assert tenant_id is not None
        return CliCommandResult(
            command="memory-tenant-queue",
            payload=read_tenant_memory_queue(
                database_path=database_path,
                tenant_id=tenant_id,
            ),
        )

    if command == "memory-tenant-queue-summary":
        assert tenant_id is not None
        return CliCommandResult(
            command="memory-tenant-queue-summary",
            payload=read_tenant_memory_queue_summary(
                database_path=database_path,
                tenant_id=tenant_id,
            ),
        )

    return None
