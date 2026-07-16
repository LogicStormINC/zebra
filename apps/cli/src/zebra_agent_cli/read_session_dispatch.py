from __future__ import annotations

from pathlib import Path

from zebra_agent_cli.approval_read import list_approvals, read_approval_detail
from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.delivery_audit_read import read_delivery_audit
from zebra_agent_cli.session_diff_read import read_session_diff
from zebra_agent_cli.session_memory_read import read_session_memory
from zebra_agent_cli.session_stream_read import read_session_stream


def read_session_dispatch(
    command: CommandName,
    *,
    database_path: Path,
    session_id: str | None = None,
    approval_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    as_of: str | None = None,
) -> CliCommandResult | None:
    if command == "approval":
        if approval_id is None:
            return CliCommandResult(
                command="approval",
                payload=list_approvals(database_path=database_path),
            )
        return CliCommandResult(
            command="approval",
            payload=read_approval_detail(
                database_path=database_path,
                approval_id=approval_id,
            ),
        )

    if command == "diff":
        assert session_id is not None
        return CliCommandResult(
            command="diff",
            payload=read_session_diff(
                database_path=database_path,
                session_id=session_id,
            ),
        )

    if command == "memory":
        assert session_id is not None
        return CliCommandResult(
            command="memory",
            payload=read_session_memory(
                database_path=database_path,
                session_id=session_id,
            ),
        )

    if command == "stream":
        assert session_id is not None
        return CliCommandResult(
            command="stream",
            payload=read_session_stream(
                database_path=database_path,
                session_id=session_id,
            ),
        )

    if command == "delivery-audit":
        assert session_id is not None
        return CliCommandResult(
            command="delivery-audit",
            payload=read_delivery_audit(
                database_path=database_path,
                session_id=session_id,
            ),
        )

    return None
