from __future__ import annotations

import argparse
from pathlib import Path

from zebra_agent_cli.approval_read import list_approvals, read_approval_detail
from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.delivery_audit_read import read_delivery_audit
from zebra_agent_cli.session_diff_read import read_session_diff
from zebra_agent_cli.session_memory_read import read_session_memory
from zebra_agent_cli.session_stream_read import read_session_stream


def add_read_subparsers(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    approval = subcommands.add_parser(
        "approval",
        help="Inspect the waiting approval queue or one approval detail.",
    )
    approval_subcommands = approval.add_subparsers(dest="approval_command", required=True)
    approval_queue = approval_subcommands.add_parser(
        "queue",
        help="List waiting approvals from the local projection store.",
    )
    approval_queue.add_argument("--database")
    approval_inspect = approval_subcommands.add_parser(
        "inspect",
        help="Inspect one waiting approval from the local projection store.",
    )
    approval_inspect.add_argument("approval_id")
    approval_inspect.add_argument("--database")

    diff = subcommands.add_parser("diff", help="Read one session workspace diff.")
    diff.add_argument("session_id")
    diff.add_argument("--database")

    memory = subcommands.add_parser("memory", help="Read one session memory inventory.")
    memory.add_argument("session_id")
    memory.add_argument("--database")

    stream = subcommands.add_parser("stream", help="Read one persisted session event stream.")
    stream.add_argument("session_id")
    stream.add_argument("--database")

    delivery_audit = subcommands.add_parser(
        "delivery-audit",
        help="Read one session delivery-audit history.",
    )
    delivery_audit.add_argument("session_id")
    delivery_audit.add_argument("--database")


def read_command_result(
    command: CommandName,
    *,
    database_path: Path,
    session_id: str | None = None,
    approval_id: str | None = None,
) -> CliCommandResult:
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
    raise ValueError(f"unsupported read command: {command}")
