from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from agent_core.domain.session_handoff import HandoffActorKind
from zebra_agent_api.session_handoff import SessionHandoffApi

from zebra_agent_cli.cli_types import CliCommandResult


def session_handoff_result(namespace: argparse.Namespace, database_path: Path) -> CliCommandResult:
    api = SessionHandoffApi(database_path)
    action = namespace.handoff_command
    if action == "inspect":
        response = api.inspect(namespace.handoff_id)
    elif action == "lineage":
        response = api.lineage(namespace.session_id)
    else:
        if action == "create" and not namespace.confirm:
            return CliCommandResult(
                command="handoff",
                payload={
                    "status": "confirmation_required",
                    "reason": "run handoff preview, then repeat create with --confirm",
                },
            )
        response = api.create(
            namespace.session_id,
            {
                "title": namespace.title,
                "objective": namespace.objective,
                "stage_prompt": namespace.stage_prompt,
                "reason": namespace.reason,
                "focus": namespace.focus,
                "completed_work": namespace.completed_work,
                "pending_work": namespace.pending_work,
            },
            idempotency_key=(namespace.idempotency_key if action == "create" else None),
            principal_identity_hash=hashlib.sha256(b"cli-local-operator").hexdigest(),
            actor_kind=HandoffActorKind.OPERATOR,
            preview=action == "preview",
        )
    return CliCommandResult(command="handoff", payload={"action": action, **response.body})
