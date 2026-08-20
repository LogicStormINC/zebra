"""PostgreSQL durable delegation store (SUBAGENT-DELEGATION-PG-01).

One transaction materializes the child Task (via the atomic admission
transaction) and its delegation link, keyed by the frozen idempotency key.
Replays return the original child — never a second Task.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_core.domain.subagent_delegation import (
    DelegationReplayError,
    ParentChildLink,
    SubagentDelegationReceipt,
    SubagentDelegationRequest,
)
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction

_INSERT_LINK = """
    INSERT INTO subagent_delegation_links (
        deployment_namespace, delegation_id, idempotency_key, root_task_id,
        parent_task_id, parent_binding_digest, child_task_id,
        child_binding_digest, plan_revision, node_key, created_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (deployment_namespace, delegation_id) DO NOTHING
    RETURNING child_task_id
"""

_SELECT_BY_KEY = """
    SELECT delegation_id, idempotency_key, root_task_id, parent_task_id,
        parent_binding_digest, child_task_id, child_binding_digest,
        plan_revision, node_key, created_at, terminal_at
    FROM subagent_delegation_links
    WHERE deployment_namespace = %s AND parent_task_id = %s AND idempotency_key = %s
"""


class PostgresSubagentDelegationStore:
    """Durable, idempotent parent→child materialization over v26."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._admission = PostgresTaskAdmissionTransaction(
            dsn, deployment_namespace=deployment_namespace
        )

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def delegate(
        self,
        request: SubagentDelegationRequest,
        child_admission: TaskAdmissionRequest,
    ) -> SubagentDelegationReceipt:
        """Materialize the child and its delegation link in ONE transaction.

        A crash can never leave an orphan child: the admission rows and
        the link commit together or roll back together. Concurrent
        delegations with the same frozen key resolve through the link's
        unique delegation_id — the loser rolls its own child back with
        the transaction and then replays the winner's link.
        """

        if child_admission.binding is not None and str(
            child_admission.binding.task_id
        ) == str(request.parent_task_id):
            raise ValueError("child admission must not rebind the parent Task")
        replay = self._find_by_key(request)
        if replay is not None:
            return _replay_receipt(request, replay)
        namespace = self.deployment_namespace
        delegation_id = request.idempotency_key
        try:
            with self._database.connect() as connection:
                replay = _find_by_key_in(connection, namespace, request)
                if replay is not None:
                    return _replay_receipt(request, replay)
                receipt = self._admission.admit_in_transaction(
                    connection, namespace, child_admission
                )
                inserted = connection.execute(
                    _INSERT_LINK,
                    (
                        namespace,
                        delegation_id,
                        request.idempotency_key,
                        str(_root_of(request)),
                        str(request.parent_task_id),
                        request.expected_parent_binding_digest,
                        str(receipt.task_id),
                        receipt.binding_digest,
                        None,
                        None,
                        datetime.now(UTC),
                    ),
                ).fetchone()
                if inserted is not None:
                    return SubagentDelegationReceipt(
                        delegation_id=delegation_id,
                        idempotency_key=request.idempotency_key,
                        child_task_id=receipt.task_id,
                        child_binding_digest=receipt.binding_digest or "0" * 64,
                    )
                # A concurrent winner committed this key first. Raising
                # rolls the loser's just-admitted child back with the
                # transaction; the except branch replays the winner.
                raise _DelegationRaceLost()
        except _DelegationRaceLost:
            winner = self._find_by_key(request)
            if winner is None:
                raise DelegationReplayError(
                    "delegation race resolved without a winner; failing closed"
                ) from None
            return _replay_receipt(request, winner)

    def child_terminal_summary(self, child_task_id: TaskId) -> str | None:
        """The child's own terminal answer from its event stream (trusted)."""

        with self._database.connect() as connection:
            return child_terminal_summary_in_transaction(
                connection, self.deployment_namespace, child_task_id
            )

    def get_link(self, child_task_id: TaskId) -> ParentChildLink | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT delegation_id, root_task_id, parent_task_id,
                    parent_binding_digest, child_binding_digest, plan_revision,
                    node_key, created_at, terminal_at
                FROM subagent_delegation_links
                WHERE deployment_namespace = %s AND child_task_id = %s
                """,
                (self.deployment_namespace, str(child_task_id)),
            ).fetchone()
        if row is None:
            return None
        return ParentChildLink(
            root_task_id=TaskId(UUID(str(row["root_task_id"]))),
            parent_task_id=TaskId(UUID(str(row["parent_task_id"]))),
            child_task_id=child_task_id,
            delegation_id=row["delegation_id"],
            parent_binding_digest=row["parent_binding_digest"],
            child_binding_digest=row["child_binding_digest"],
            plan_revision=row["plan_revision"],
            node_key=row["node_key"],
            created_at=row["created_at"],
            terminal_at=row["terminal_at"],
        )

    def _find_by_key(
        self, request: SubagentDelegationRequest
    ) -> ParentChildLink | None:
        with self._database.connect() as connection:
            return _find_by_key_in(connection, self.deployment_namespace, request)


def _replay_receipt(
    request: SubagentDelegationRequest, replay: ParentChildLink
) -> SubagentDelegationReceipt:
    return SubagentDelegationReceipt(
        delegation_id=replay.delegation_id,
        idempotency_key=request.idempotency_key,
        child_task_id=replay.child_task_id,
        child_binding_digest=replay.child_binding_digest or "0" * 64,
        status="replayed",
    )


def _find_by_key_in(
    connection: Any,
    namespace: str,
    request: SubagentDelegationRequest,
) -> ParentChildLink | None:
    row = connection.execute(
        _SELECT_BY_KEY,
        (
            namespace,
            str(request.parent_task_id),
            request.idempotency_key,
        ),
    ).fetchone()
    if row is None:
        return None
    return ParentChildLink(
        root_task_id=TaskId(UUID(str(row["root_task_id"]))),
        parent_task_id=TaskId(UUID(str(row["parent_task_id"]))),
        child_task_id=TaskId(UUID(str(row["child_task_id"]))),
        delegation_id=row["delegation_id"],
        parent_binding_digest=row["parent_binding_digest"],
        child_binding_digest=row["child_binding_digest"],
        plan_revision=row["plan_revision"],
        node_key=row["node_key"],
        created_at=row["created_at"],
        terminal_at=row["terminal_at"],
    )


def _root_of(request: SubagentDelegationRequest) -> TaskId:
    """Until the orchestration graph lands, the parent is the root."""

    return request.parent_task_id


class _DelegationRaceLost(Exception):
    """A concurrent delegation won this key; replay it after rollback."""


def child_terminal_summary_in_transaction(
    connection: Any,
    namespace: str,
    child_task_id: TaskId,
) -> str | None:
    """Read one child's canonical terminal answer from its OWN event stream.

    The real model answer lives in the terminal event's
    ``metadata.assistant_message``; the top-level ``summary`` is only a
    harness lifecycle label. Cancelled children carry no answer, so the
    fallback text is their canonical summary. The result is truncated to
    a UTF-8-safe BYTE budget so worst-case epochs (16 children) stay far
    inside the 64 KiB command contract; producer and verifier share this
    canonical form, so equality checks remain exact.
    """

    row = connection.execute(
        """
        SELECT payload FROM session_events
        WHERE deployment_namespace = %s AND session_id = %s
            AND event_type IN ('session_completed', 'session_failed', 'session_cancelled')
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (namespace, str(child_task_id)),
    ).fetchone()
    if row is None:
        return None
    payload = row["payload"]
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    if isinstance(metadata, dict):
        assistant = metadata.get("assistant_message")
        if isinstance(assistant, str) and assistant.strip():
            return _canonical_summary(assistant)
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if isinstance(summary, str) and summary.strip():
        return _canonical_summary(summary)
    return _CANONICAL_FALLBACK_SUMMARY


_CANONICAL_FALLBACK_SUMMARY = "child reached a terminal status"
# The command contract measures json.dumps(payload, ensure_ascii=True)
# bytes (CJK escapes to 6 bytes/char), so the canonical form budgets the
# summary's JSON-escaped size — not raw UTF-8. Worst case is 16 children
# (ParentContinuation.MAX_CHILDREN): 16 × 3 KiB + entry/envelope
# overhead stays well inside the 64 KiB command payload limit.
_PER_SUMMARY_JSON_BUDGET = 3 * 1024


def _json_bytes(value: str) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _canonical_summary(text: str) -> str:
    stripped = text.strip()
    candidate = stripped
    while candidate:
        if _json_bytes(candidate) <= _PER_SUMMARY_JSON_BUDGET:
            break
        excess = _json_bytes(candidate) - _PER_SUMMARY_JSON_BUDGET
        cut = min(len(candidate), excess + 16)
        candidate = candidate[: len(candidate) - cut].rstrip()
    # Both ends stay whitespace-free so the recovery side's defensive
    # strip can never rewrite the canonical value the verifier compares
    # against (a truncation boundary may legally land after a space).
    return candidate or _CANONICAL_FALLBACK_SUMMARY
