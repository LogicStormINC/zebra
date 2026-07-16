from __future__ import annotations

from pathlib import Path

from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.session_memory_read import (
    read_session_memory_overdue_retention_breach_actions,
    read_session_memory_overdue_retention_breach_aging,
    read_session_memory_overdue_retention_breach_follow_through_completion_states,
    read_session_memory_overdue_retention_breach_follow_through_modes,
    read_session_memory_overdue_retention_breach_follow_through_outcomes,
    read_session_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_session_memory_overdue_retention_breach_follow_through_verification_states,
    read_session_memory_overdue_retention_breach_lanes,
    read_session_memory_overdue_retention_breach_owner_targets,
    read_session_memory_overdue_retention_breaches,
    read_session_memory_overdue_retention_windows,
)


def read_memory_retention_dispatch(
    command: CommandName,
    *,
    database_path: Path,
    session_id: str | None = None,
    approval_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    as_of: str | None = None,
) -> CliCommandResult | None:
    if command == "memory-overdue-retention-windows":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-windows",
            payload=read_session_memory_overdue_retention_windows(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-breaches":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breaches",
            payload=read_session_memory_overdue_retention_breaches(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-breach-aging":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-aging",
            payload=read_session_memory_overdue_retention_breach_aging(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-breach-actions":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-actions",
            payload=read_session_memory_overdue_retention_breach_actions(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-breach-lanes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-lanes",
            payload=read_session_memory_overdue_retention_breach_lanes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-breach-owner-targets":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-owner-targets",
            payload=read_session_memory_overdue_retention_breach_owner_targets(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-breach-follow-through-modes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-modes",
            payload=read_session_memory_overdue_retention_breach_follow_through_modes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-breach-follow-through-outcomes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-outcomes",
            payload=read_session_memory_overdue_retention_breach_follow_through_outcomes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-retention-breach-follow-through-completion-states":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-completion-states",
            payload=(
                read_session_memory_overdue_retention_breach_follow_through_completion_states(
                    database_path=database_path,
                    session_id=session_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    as_of=as_of,
                )
            ),
        )

    if command == "memory-overdue-retention-breach-follow-through-verification-states":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-verification-states",
            payload=(
                read_session_memory_overdue_retention_breach_follow_through_verification_states(
                    database_path=database_path,
                    session_id=session_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    as_of=as_of,
                )
            ),
        )

    if command == "memory-overdue-retention-breach-follow-through-verification-outcomes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-verification-outcomes",
            payload=(
                read_session_memory_overdue_retention_breach_follow_through_verification_outcomes(
                    database_path=database_path,
                    session_id=session_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    as_of=as_of,
                )
            ),
        )

    return None
