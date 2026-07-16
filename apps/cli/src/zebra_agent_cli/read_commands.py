from __future__ import annotations

from pathlib import Path

from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.read_command_parsing import add_read_subparsers
from zebra_agent_cli.read_memory_governance_dispatch import read_memory_governance_dispatch
from zebra_agent_cli.read_memory_pressure_dispatch import read_memory_pressure_dispatch
from zebra_agent_cli.read_memory_resolution_dispatch import read_memory_resolution_dispatch
from zebra_agent_cli.read_memory_retention_dispatch import read_memory_retention_dispatch
from zebra_agent_cli.read_session_dispatch import read_session_dispatch


def read_command_result(
    command: CommandName,
    *,
    database_path: Path,
    session_id: str | None = None,
    approval_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    as_of: str | None = None,
) -> CliCommandResult:
    if result := read_session_dispatch(
        command,
        database_path=database_path,
        session_id=session_id,
        approval_id=approval_id,
        user_id=user_id,
        tenant_id=tenant_id,
        as_of=as_of,
    ):
        return result
    if result := read_memory_pressure_dispatch(
        command,
        database_path=database_path,
        session_id=session_id,
        approval_id=approval_id,
        user_id=user_id,
        tenant_id=tenant_id,
        as_of=as_of,
    ):
        return result
    if result := read_memory_resolution_dispatch(
        command,
        database_path=database_path,
        session_id=session_id,
        approval_id=approval_id,
        user_id=user_id,
        tenant_id=tenant_id,
        as_of=as_of,
    ):
        return result
    if result := read_memory_retention_dispatch(
        command,
        database_path=database_path,
        session_id=session_id,
        approval_id=approval_id,
        user_id=user_id,
        tenant_id=tenant_id,
        as_of=as_of,
    ):
        return result
    if result := read_memory_governance_dispatch(
        command,
        database_path=database_path,
        session_id=session_id,
        approval_id=approval_id,
        user_id=user_id,
        tenant_id=tenant_id,
        as_of=as_of,
    ):
        return result
    raise ValueError(f"unsupported read command: {command}")


__all__ = ("add_read_subparsers", "read_command_result")
