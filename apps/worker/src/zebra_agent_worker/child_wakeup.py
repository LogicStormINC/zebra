"""Child-completion wakeup service (Phase F4, real implementation).

Polls delegation links for children that reached a terminal Session
status. Marking a child terminal does NOT by itself wake the parent:
the service loads the durable ``ParentContinuation`` and evaluates the
completion strategy — the parent only resumes once every child of the
current delegation epoch is terminal, and the wakeup command then
carries every child's REAL terminal answer (read back from each child's
own event stream, never from caller input). Command append and link
terminal update share one transaction.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.parent_continuation import (
    ChildTerminalRecord,
    ChildTerminalStatus,
    ContinuationDecision,
    ParentContinuation,
)
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.subagent_delegation import (
    child_terminal_summary_in_transaction,
)

_STATUS_MAP: dict[str, ChildTerminalStatus] = {
    SessionStatus.COMPLETED.value: ChildTerminalStatus.COMPLETED,
    SessionStatus.FAILED.value: ChildTerminalStatus.FAILED,
    SessionStatus.CANCELLED.value: ChildTerminalStatus.CANCELLED,
}

_POLL_LIMIT = 16
_WAKEUP_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


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
                    "child_task_id": TaskId(UUID(str(row["child_task_id"]))),
                    "parent_task_id": TaskId(UUID(str(row["parent_task_id"]))),
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
        """Mark the child terminal, then wake the parent only when settled.

        The resume command is emitted by the HARNESS actor and carries the
        real terminal answer of EVERY child in the current delegation
        epoch, re-read from each child's own event stream inside the same
        transaction. Until the continuation settles, only the link is
        marked terminal — no premature wakeup.
        """

        parent = self._find_parent(child_task_id)
        if parent is None:
            return None
        parent_session = SessionId(parent)
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            # Serialize wakeup processing per parent: the stream row lock
            # orders every claim → evaluate → emit sequence for this
            # parent, so concurrent workers can neither duplicate the
            # wakeup event nor both observe keep_waiting and strand it.
            locked = connection.execute(
                """
                SELECT current_version FROM session_streams
                WHERE deployment_namespace = %s AND session_id = %s
                FOR UPDATE
                """,
                (namespace, str(parent_session)),
            ).fetchone()
            if locked is None:
                return None
            connection.execute(
                """
                UPDATE subagent_delegation_links
                SET terminal_at = %s
                WHERE deployment_namespace = %s AND child_task_id = %s
                    AND terminal_at IS NULL
                """,
                (datetime.now(UTC), namespace, str(child_task_id)),
            )
            continuation = self._load_continuation_in(connection, namespace, parent)
            if continuation is None:
                return None
            terminals = self._terminal_records(connection, namespace, parent)
            decision, relevant = continuation.evaluate(terminals)
            if decision is not ContinuationDecision.RESUME:
                return {
                    "parent_task_id": str(parent),
                    "child_task_id": str(child_task_id),
                    "decision": "keep_waiting",
                    "reason": "children_outstanding",
                    "settled_child_count": len(relevant),
                    "required_child_count": len(continuation.required_child_ids),
                }
            child_results: list[dict[str, str]] = []
            for record in sorted(relevant, key=lambda item: str(item.child_task_id)):
                summary = child_terminal_summary_in_transaction(
                    connection, namespace, record.child_task_id
                )
                child_results.append(
                    {
                        "child_task_id": str(record.child_task_id),
                        "status": record.status.value,
                        "summary": summary or "child reached a terminal status",
                    }
                )
            current = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) AS current_sequence
                FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (namespace, str(parent_session)),
            ).fetchone()
            assert current is not None
            next_sequence = int(current["current_sequence"]) + 1
            # The wakeup event is DETERMINISTIC per settled epoch so the
            # event idempotency dedupe accepts concurrent processors:
            # sorted children, an epoch-derived command id, and an
            # expected_revision anchored to the epoch's own last
            # delegation (not the evolving stream head).
            epoch_children = sorted(
                str(record.child_task_id) for record in relevant
            )
            epoch_digest = hashlib.sha256(
                ":".join(epoch_children).encode()
            ).hexdigest()
            epoch_anchor = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS anchored_revision
                FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                    AND event_type = 'subagent_delegated'
                """,
                (namespace, str(parent_session)),
            ).fetchone()
            assert epoch_anchor is not None
            event = SessionEvent.create(
                session_id=parent_session,
                sequence=next_sequence,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.HARNESS,
                payload={
                    "command_id": str(
                        uuid5(_WAKEUP_NAMESPACE, f"wakeup:{parent}:{epoch_digest}")
                    ),
                    "session_id": str(parent_session),
                    "kind": "resume",
                    "expected_revision": int(epoch_anchor["anchored_revision"]),
                    "idempotency_key": f"child-wakeup:{parent}",
                    "payload": {"child_results": child_results},
                    "fingerprint": _command_fingerprint(
                        f"{parent}:{epoch_digest}", "resume"
                    ),
                },
                created_at=datetime.now(UTC),
                idempotency_key=f"wakeup:{parent}:{epoch_digest}",
            )
            self._append_event(connection, namespace, event)
        return {
            "parent_task_id": str(parent),
            "child_task_id": str(child_task_id),
            "decision": "resume",
            "reason": "children_terminal",
            "settled_child_count": len(relevant),
            "any_success": any(
                record.status is ChildTerminalStatus.COMPLETED for record in relevant
            ),
        }

    def load_parent_continuation(
        self, parent_task_id: TaskId
    ) -> ParentContinuation | None:
        """Rebuild the durable continuation for the CURRENT delegation epoch.

        The epoch is every ``SUBAGENT_DELEGATED`` event after the last
        resume/terminal boundary that still has a delegation after it —
        children settled in earlier epochs no longer gate this one.
        """

        with self._database.connect() as connection:
            return self._load_continuation_in(
                connection, self.deployment_namespace, parent_task_id
            )

    def _load_continuation_in(
        self, connection: Any, namespace: str, parent_task_id: TaskId
    ) -> ParentContinuation | None:
        rows = connection.execute(
                """
                SELECT event_type, payload, created_at FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                    AND event_type IN (
                        'subagent_delegated', 'session_resumed',
                        'session_completed', 'session_failed', 'session_cancelled'
                    )
                ORDER BY sequence
                """,
                (namespace, str(parent_task_id)),
            ).fetchall()
        delegated_indexes = [
            index
            for index, row in enumerate(rows)
            if row["event_type"] == "subagent_delegated"
        ]
        if not delegated_indexes:
            return None
        cut = -1
        for index, row in enumerate(rows):
            if row["event_type"] == "subagent_delegated":
                continue
            if any(delegated > index for delegated in delegated_indexes):
                cut = index
        epoch: list[TaskId] = []
        created_at = datetime.now(UTC)
        seen: set[str] = set()
        for index in delegated_indexes:
            if index <= cut:
                continue
            payload = rows[index]["payload"] or {}
            child_id = payload.get("child_task_id") if isinstance(payload, dict) else None
            if not isinstance(child_id, str) or not child_id.strip():
                continue
            normalized = child_id.strip()
            if normalized not in seen:
                seen.add(normalized)
                epoch.append(TaskId(UUID(normalized)))
                created_at = rows[index]["created_at"]
        if not epoch:
            return None
        return ParentContinuation(
            parent_task_id=parent_task_id,
            plan_revision=1,
            required_child_ids=tuple(epoch),
            completion_strategy="all_terminal",
            resume_command_key=f"child-wakeup:{parent_task_id}",
            created_at=created_at,
        )

    def _terminal_records(
        self, connection: Any, namespace: str, parent: TaskId
    ) -> tuple[ChildTerminalRecord, ...]:
        rows = connection.execute(
            """
            SELECT link.child_task_id, link.terminal_at, proj.status
            FROM subagent_delegation_links link
            LEFT JOIN session_projections proj
                ON proj.deployment_namespace = link.deployment_namespace
                AND proj.session_id = link.child_task_id
            WHERE link.deployment_namespace = %s AND link.parent_task_id = %s
            """,
            (namespace, str(parent)),
        ).fetchall()
        records: list[ChildTerminalRecord] = []
        for row in rows:
            mapped = _STATUS_MAP.get(row["status"])
            if mapped is None or row["terminal_at"] is None:
                continue
            child_id = TaskId(UUID(str(row["child_task_id"])))
            summary = child_terminal_summary_in_transaction(
                connection, namespace, child_id
            )
            records.append(
                ChildTerminalRecord(
                    child_task_id=child_id,
                    status=mapped,
                    result_bundle_digest=(
                        hashlib.sha256((summary or "").encode()).hexdigest()
                        if mapped is ChildTerminalStatus.COMPLETED
                        else None
                    ),
                    terminal_at=row["terminal_at"],
                )
            )
        return tuple(records)

    def _load_continuation(self, parent_task_id: TaskId) -> ParentContinuation | None:
        return self.load_parent_continuation(parent_task_id)

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
        return TaskId(UUID(str(row["parent_task_id"])))


def _command_fingerprint(session_id: str, kind: str) -> str:
    return hashlib.sha256(f"{session_id}:{kind}".encode()).hexdigest()
