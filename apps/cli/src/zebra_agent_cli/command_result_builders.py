from __future__ import annotations

import argparse
from pathlib import Path

from zebra_agent_config import ZebraAgentSettings

from zebra_agent_cli.approval_decision_write import record_approval_decision
from zebra_agent_cli.artifact_read import (
    list_artifacts,
    prune_artifact,
    read_artifact_content,
    read_artifact_detail,
)
from zebra_agent_cli.cli_database import (
    _database_path,
)
from zebra_agent_cli.cli_types import CliCommandResult
from zebra_agent_cli.session_suspend_write import suspend_session


def _suspend_result(
    namespace: argparse.Namespace,
    settings: ZebraAgentSettings,
) -> CliCommandResult:
    return CliCommandResult(
        command="suspend",
        payload=suspend_session(
            database_path=_database_path(namespace.database, settings),
            session_id=namespace.session_id,
        ),
    )


def _approval_result(
    namespace: argparse.Namespace,
    database_path: Path,
) -> CliCommandResult:
    return CliCommandResult(
        command="approve",
        payload=record_approval_decision(
            database_path=database_path,
            approval_id=namespace.session_id,
            decision=namespace.decision,
            operator=namespace.operator,
            reason=namespace.reason,
        ),
    )


def _artifact_result(
    namespace: argparse.Namespace,
    database_path: Path,
) -> CliCommandResult:
    if namespace.artifact_command == "list":
        payload = list_artifacts(
            database_path=database_path,
            session_id=namespace.session_id,
        )
        return CliCommandResult(command="artifact", payload=payload)
    if namespace.artifact_command == "inspect":
        payload = read_artifact_detail(
            database_path=database_path,
            session_id=namespace.session_id,
            artifact_id=namespace.artifact_id,
        )
        return CliCommandResult(command="artifact", payload=payload)
    if namespace.artifact_command == "read":
        payload = read_artifact_content(
            database_path=database_path,
            session_id=namespace.session_id,
            artifact_id=namespace.artifact_id,
        )
        return CliCommandResult(command="artifact", payload=payload)
    if namespace.artifact_command == "prune":
        payload = prune_artifact(
            database_path=database_path,
            session_id=namespace.session_id,
            artifact_id=namespace.artifact_id,
        )
        return CliCommandResult(command="artifact", payload=payload)
    raise ValueError(f"unsupported artifact command: {namespace.artifact_command}")
