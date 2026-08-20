"""PostgreSQL durable delegation store (SUBAGENT-DELEGATION-PG-01).

One transaction materializes the child Task (via the atomic admission
transaction) and its delegation link, keyed by the frozen idempotency key.
Replays return the original child — never a second Task.
"""

from __future__ import annotations

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
        unique delegation_id — the loser rolls its child back and
        replays the winner's.
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
            if inserted is None:
                existing = _find_by_key_in(connection, namespace, request)
                if existing is None or str(existing.child_task_id) != str(receipt.task_id):
                    # Raising inside the transaction rolls the orphan child
                    # back with the failed link insert.
                    raise DelegationReplayError(
                        "delegation key resolved to a different child; failing closed"
                    )
                return _replay_receipt(request, existing)
            return SubagentDelegationReceipt(
                delegation_id=delegation_id,
                idempotency_key=request.idempotency_key,
                child_task_id=receipt.task_id,
                child_binding_digest=receipt.binding_digest or "0" * 64,
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
