"""Child-completion wakeup service (Phase F4).

Polls delegation links for terminal children, evaluates parent
continuations, and emits durable resume commands when strategies settle.
This is the "Child terminal → Parent wakeup" leg of the E2E chain.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent_core.domain.identifiers import TaskId
from agent_core.domain.parent_continuation import (
    ChildTerminalRecord,
    ChildTerminalStatus,
    ParentContinuation,
    evaluate_wakeup,
)


class ChildCompletionWakeupService:
    """Evaluates child terminals against parent continuations."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        from agent_storage.postgres.database import PostgresDatabase

        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def process_child_terminal(
        self,
        child_task_id: TaskId,
        *,
        status: ChildTerminalStatus,
        result_bundle_digest: str | None = None,
    ) -> dict[str, object] | None:
        """Record a child terminal and evaluate the parent wakeup.

        Returns the wakeup payload when the strategy settles, or None.
        The payload is a durable resume-command body; the caller writes it
        into the parent's command queue.
        """

        terminal = ChildTerminalRecord(
            child_task_id=child_task_id,
            status=status,
            result_bundle_digest=result_bundle_digest,
            terminal_at=datetime.now(UTC),
        )
        parent = self._find_parent(child_task_id)
        if parent is None:
            return None
        continuation = self._load_continuation(parent)
        if continuation is None:
            # No continuation: direct wakeup (single-child delegation)
            return {
                "parent_task_id": str(parent),
                "child_task_id": str(child_task_id),
                "decision": "resume",
                "reason": "child_terminal_no_continuation",
                "any_success": status is ChildTerminalStatus.COMPLETED,
            }
        wakeup = evaluate_wakeup(continuation, (terminal,))
        if wakeup is None:
            return None
        return {
            "parent_task_id": str(continuation.parent_task_id),
            "child_task_id": str(child_task_id),
            "decision": "resume",
            "reason": "strategy_settled",
            "resume_command_key": continuation.resume_command_key,
            "any_success": wakeup.any_success,
            "settled_children": wakeup.settled_child_count,
        }

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

        v1: continuations are serialized as JSONB in the orchestration
        plan_revisions snapshot (the parent_binding carries the
        resume_command_key). Until dedicated continuation storage lands,
        a single-child delegation resumes directly.
        """

        return None
