"""Child-completion wakeup service (Phase F4, real implementation).

Polls delegation links for children that reached a terminal Session
status, then appends a SESSION_COMMAND_ACCEPTED event to the PARENT's
event stream. The existing SessionCommandConsumer picks it up and
re-executes the parent on its next poll cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.parent_continuation import (
    ChildTerminalStatus,
    ParentContinuation,
)
from agent_core.domain.sessions import SessionStatus

_STATUS_MAP: dict[str, ChildTerminalStatus] = {
    SessionStatus.COMPLETED.value: ChildTerminalStatus.COMPLETED,
    SessionStatus.FAILED.value: ChildTerminalStatus.FAILED,
    SessionStatus.CANCELLED.value: ChildTerminalStatus.CANCELLED,
}

_POLL_LIMIT = 16


class ChildCompletionWakeupService:
    """Evaluates terminal children and wakes parents via Event Store commands."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        from agent_storage.postgres.database import PostgresDatabase
        from agent_storage.postgres.events import append_event_in_transaction

        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._append_event = append_event_in_transaction

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def poll_terminal_children(self) -> list[dict[str, object]]:
        """Find children with terminal Session status that have delegation links."""

        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT link.child_task_id, link.parent_task_id,
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
        """Append a resume command to the parent's event stream, then mark the link.

        Order matters: the command event must land BEFORE the link is
        marked terminal, so a crash between the two leaves the child
        re-processable rather than lost.
        """

        parent = self._find_parent(child_task_id)
        if parent is None:
            return None
        parent_session = SessionId(parent)
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            current = connection.execute(
                """
                SELECT current_sequence FROM session_projections
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (namespace, str(parent_session)),
            ).fetchone()
            if current is None:
                return None
            next_sequence = int(current["current_sequence"]) + 1
            event = SessionEvent.create(
                session_id=parent_session,
                sequence=next_sequence,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.HARNESS,
                payload={
                    "command_id": str(uuid4()),
                    "session_id": str(parent_session),
                    "kind": "resume",
                    "expected_revision": int(current["current_sequence"]),
                    "idempotency_key": f"child-wakeup:{child_task_id}",
                    "payload": {},
                    "fingerprint": _command_fingerprint(str(parent_session), "resume"),
                },
                created_at=datetime.now(UTC),
            )
            self._append_event(connection, namespace, event)
            # Mark the link terminal in the SAME transaction (atomic wakeup)
            connection.execute(
                """
                UPDATE subagent_delegation_links
                SET terminal_at = %s
                WHERE deployment_namespace = %s AND child_task_id = %s
                    AND terminal_at IS NULL
                """,
                (datetime.now(UTC), namespace, str(child_task_id)),
            )
        return {
            "parent_task_id": str(parent),
            "child_task_id": str(child_task_id),
            "decision": "resume",
            "reason": "child_terminal",
            "any_success": status is ChildTerminalStatus.COMPLETED,
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
        """Load a stored parent continuation (ORCH-PG projections)."""

        return None

def _command_fingerprint(session_id: str, kind: str) -> str:
    import hashlib

    return hashlib.sha256(f"{session_id}:{kind}".encode()).hexdigest()
