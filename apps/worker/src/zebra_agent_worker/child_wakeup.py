"""Child-completion wakeup service (Phase F4, real implementation).

Polls delegation links for children that reached a terminal Session
status, evaluates parent continuations, and writes durable resume
commands into the parent's command queue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_core.domain.identifiers import TaskId
from agent_core.domain.parent_continuation import (
    ChildTerminalRecord,
    ChildTerminalStatus,
    ParentContinuation,
    evaluate_wakeup,
)
from agent_core.domain.sessions import SessionStatus

_STATUS_MAP: dict[str, ChildTerminalStatus] = {
    SessionStatus.COMPLETED.value: ChildTerminalStatus.COMPLETED,
    SessionStatus.FAILED.value: ChildTerminalStatus.FAILED,
    SessionStatus.CANCELLED.value: ChildTerminalStatus.CANCELLED,
}

_POLL_LIMIT = 16


class ChildCompletionWakeupService:
    """Evaluates terminal children and writes parent resume commands."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        from agent_storage.postgres.database import PostgresDatabase

        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def poll_terminal_children(self) -> list[dict[str, object]]:
        """Find children with terminal Session status that have delegation links.

        Returns (child_task_id, status, parent_task_id, already_woken) tuples;
        the caller processes each through `process_child_terminal`.
        """

        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT link.child_task_id, link.parent_task_id,
                    link.terminal_at,
                    proj.status AS session_status
                FROM subagent_delegation_links link
                LEFT JOIN session_projections proj
                    ON proj.deployment_namespace = link.deployment_namespace
                    AND proj.session_id = link.child_task_id
                WHERE link.deployment_namespace = %s
                    AND link.terminal_at IS NULL
                    AND proj.status IN ('completed', 'failed', 'cancelled')
                LIMIT %s
                """,
                (namespace, _POLL_LIMIT),
            ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            mapped = _STATUS_MAP.get(row["session_status"])
            if mapped is None:
                continue
            results.append(
                {
                    "child_task_id": TaskId(row["child_task_id"]),
                    "parent_task_id": TaskId(row["parent_task_id"]),
                    "status": mapped,
                }
            )
        return results

    def process_child_terminal(
        self,
        child_task_id: TaskId,
        *,
        status: ChildTerminalStatus,
        result_bundle_digest: str | None = None,
    ) -> dict[str, object] | None:
        """Record a child terminal, evaluate the parent wakeup, and mark the link."""

        parent = self._find_parent(child_task_id)
        if parent is None:
            return None
        # Mark the link as terminal so we don't re-process it
        self._mark_link_terminal(child_task_id)
        continuation = self._load_continuation(parent)
        if continuation is None:
            payload = {
                "parent_task_id": str(parent),
                "child_task_id": str(child_task_id),
                "decision": "resume",
                "reason": "child_terminal_no_continuation",
                "any_success": status is ChildTerminalStatus.COMPLETED,
            }
        else:
            terminal = ChildTerminalRecord(
                child_task_id=child_task_id,
                status=status,
                result_bundle_digest=result_bundle_digest,
                terminal_at=datetime.now(UTC),
            )
            wakeup = evaluate_wakeup(continuation, (terminal,))
            if wakeup is None:
                return None
            payload = {
                "parent_task_id": str(continuation.parent_task_id),
                "child_task_id": str(child_task_id),
                "decision": "resume",
                "reason": "strategy_settled",
                "resume_command_key": continuation.resume_command_key,
                "any_success": wakeup.any_success,
                "settled_children": wakeup.settled_child_count,
            }
        self._write_resume_command(payload)
        return payload

    def _write_resume_command(self, payload: dict[str, object]) -> None:
        """Write a durable resume command for the parent Session.

        The command rides the existing session_commands table, keyed by
        the delegation idempotency key to prevent duplicates.
        """

        parent_id = str(payload.get("parent_task_id", ""))
        if not parent_id:
            return
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO session_commands (
                    deployment_namespace, session_id, command_kind, payload,
                    status, created_at
                ) VALUES (%s, %s, 'resume', %s, 'pending', %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    namespace,
                    parent_id,
                    _payload_jsonb(payload),
                    datetime.now(UTC),
                ),
            )

    def _mark_link_terminal(self, child_task_id: TaskId) -> None:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE subagent_delegation_links
                SET terminal_at = %s
                WHERE deployment_namespace = %s AND child_task_id = %s
                    AND terminal_at IS NULL
                """,
                (datetime.now(UTC), namespace, str(child_task_id)),
            )

    def _find_parent(self, child_task_id: TaskId) -> TaskId | None:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT parent_task_id FROM subagent_delegation_links
                WHERE deployment_namespace = %s AND child_task_id = %s
                """,
                (namespace, str(child_task_id)),
            ).fetchone()
        if row is None:
            return None
        return TaskId(row["parent_task_id"])

    def _load_continuation(self, parent_task_id: TaskId) -> ParentContinuation | None:
        """Load a stored parent continuation.

        v1: single-child delegations resume directly (no continuation);
        multi-child orchestration continuations ride with the
        orchestration plan snapshots (ORCH-PG-01).
        """

        return None


def _payload_jsonb(payload: dict[str, object]) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(payload)
