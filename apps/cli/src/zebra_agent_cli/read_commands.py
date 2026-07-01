from __future__ import annotations

import argparse
from pathlib import Path

from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.delivery_audit_read import read_delivery_audit
from zebra_agent_cli.session_diff_read import read_session_diff
from zebra_agent_cli.session_stream_read import read_session_stream


def add_read_subparsers(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    diff = subcommands.add_parser("diff", help="Read one session workspace diff.")
    diff.add_argument("session_id")
    diff.add_argument("--database")

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
    session_id: str,
    database_path: Path,
) -> CliCommandResult:
    if command == "diff":
        return CliCommandResult(
            command="diff",
            payload=read_session_diff(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    if command == "stream":
        return CliCommandResult(
            command="stream",
            payload=read_session_stream(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    if command == "delivery-audit":
        return CliCommandResult(
            command="delivery-audit",
            payload=read_delivery_audit(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    raise ValueError(f"unsupported read command: {command}")
