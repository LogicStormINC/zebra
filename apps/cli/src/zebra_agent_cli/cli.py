from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_core.domain.sessions import Session
from agent_storage import SQLiteProjectionStore

CommandName = Literal["run", "resume", "inspect", "approve"]


@dataclass(frozen=True)
class CliCommandResult:
    command: CommandName
    payload: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(
            {
                "command": self.command,
                **self.payload,
            },
            sort_keys=True,
        )


def execute(argv: Sequence[str]) -> CliCommandResult:
    namespace = _parser().parse_args(list(argv))
    command = namespace.command
    if command == "run":
        return _run_result(namespace)
    if command == "resume":
        return _session_result("resume", namespace.session_id)
    if command == "inspect":
        return _session_result("inspect", namespace.session_id)
    if command == "approve":
        return _approval_result(namespace)
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
    run.add_argument("--database", default=".zebra-agent/sessions.sqlite")

    resume = subcommands.add_parser("resume", help="Resume a suspended session.")
    resume.add_argument("session_id")

    inspect = subcommands.add_parser("inspect", help="Inspect a session.")
    inspect.add_argument("session_id")

    approve = subcommands.add_parser("approve", help="Record an approval decision.")
    approve.add_argument("approval_id")
    approve.add_argument("--decision", choices=("approve", "reject"), required=True)
    approve.add_argument("--reason", default="")

    return parser


def _run_result(namespace: argparse.Namespace) -> CliCommandResult:
    session = Session.create(title=namespace.title)
    database_path = Path(namespace.database)
    SQLiteProjectionStore(database_path).save_session(session)
    return CliCommandResult(
        command="run",
        payload={
            "session_id": str(session.session_id),
            "title": namespace.title,
            "prompt": namespace.prompt,
            "workspace": str(Path(namespace.workspace)),
            "database": str(database_path),
            "status": session.status.value,
        },
    )


def _session_result(command: CommandName, session_id: str) -> CliCommandResult:
    return CliCommandResult(
        command=command,
        payload={
            "session_id": session_id,
            "status": "accepted",
        },
    )


def _approval_result(namespace: argparse.Namespace) -> CliCommandResult:
    return CliCommandResult(
        command="approve",
        payload={
            "approval_id": namespace.approval_id,
            "decision": namespace.decision,
            "reason": namespace.reason,
            "status": "accepted",
        },
    )
