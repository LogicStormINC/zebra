from __future__ import annotations

from pathlib import Path

from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.session_memory_read import (
    read_session_memory_action_hints,
    read_session_memory_escalations,
    read_session_memory_follow_up_windows,
    read_session_memory_overdue_age_buckets,
    read_session_memory_overdue_escalation_lanes,
    read_session_memory_overdue_flags,
    read_session_memory_overdue_intervention_hints,
    read_session_memory_overdue_recovery_paths,
    read_session_memory_overdue_trend_signals,
    read_session_memory_overdue_type_rollups,
    read_session_memory_overdue_visibility_rollups,
)


def read_memory_pressure_dispatch(
    command: CommandName,
    *,
    database_path: Path,
    session_id: str | None = None,
    approval_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    as_of: str | None = None,
) -> CliCommandResult | None:
    if command == "memory-action-hints":
        assert session_id is not None
        return CliCommandResult(
            command="memory-action-hints",
            payload=read_session_memory_action_hints(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-escalations":
        assert session_id is not None
        return CliCommandResult(
            command="memory-escalations",
            payload=read_session_memory_escalations(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-follow-up-windows":
        assert session_id is not None
        return CliCommandResult(
            command="memory-follow-up-windows",
            payload=read_session_memory_follow_up_windows(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-flags":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-flags",
            payload=read_session_memory_overdue_flags(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-age-buckets":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-age-buckets",
            payload=read_session_memory_overdue_age_buckets(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-types":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-types",
            payload=read_session_memory_overdue_type_rollups(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-visibility":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-visibility",
            payload=read_session_memory_overdue_visibility_rollups(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-trends":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-trends",
            payload=read_session_memory_overdue_trend_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-interventions":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-interventions",
            payload=read_session_memory_overdue_intervention_hints(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-escalation-lanes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-escalation-lanes",
            payload=read_session_memory_overdue_escalation_lanes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    if command == "memory-overdue-recovery-paths":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-recovery-paths",
            payload=read_session_memory_overdue_recovery_paths(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )

    return None
