"""Atomic native Registry mutation and publication receipts under current approval."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementStore,
    HostManagementTrust,
)
from agent_storage.postgres.work_unit import postgres_transaction_work_unit


class PublicationStore:
    def __init__(self, dsn: str, namespace: str) -> None:
        self.database = PostgresDatabase(dsn, deployment_namespace=namespace)
        self.approvals = HostManagementStore(dsn, deployment_namespace=namespace)

    def read(self, trust: HostManagementTrust, operation: str) -> dict[str, Any] | None:
        with self.approvals.authorized(trust) as connection:
            row = self._receipt(connection, trust, operation)
            self.approvals._live(connection, trust)
            return dict(row["result"]) if row is not None else None

    def apply(
        self,
        trust: HostManagementTrust,
        operation: str,
        digest: str,
        scope_key: tuple[str, str, Any],
        expected: int,
        mutate: Callable[[], dict[str, Any]],
        recheck: Callable[[], None],
    ) -> dict[str, Any]:
        with self.approvals.authorized(trust) as connection:
            lock_definition(connection, scope_key)
            row = self._receipt(connection, trust, operation)
            if row is not None:
                if row["payload_digest"] != digest:
                    raise HostManagementConflict("OPERATION_CONFLICT")
                recheck()
                return dict(row["result"])
            key = (self.database.deployment_namespace, *scope_key)
            head = connection.execute(
                "SELECT revision FROM runtime_publication_heads WHERE "
                "deployment_namespace=%s AND authority_issuer=%s "
                "AND namespace_id=%s AND definition_id=%s",
                key,
            ).fetchone()
            if (0 if head is None else int(head["revision"])) != expected:
                raise HostManagementConflict("REVISION_CONFLICT")
            # Registry borrows this transaction; partial Version/Release writes roll back.
            with postgres_transaction_work_unit(self.database, connection):
                result = mutate()
            result.update(operationId=operation, revision=expected + 1, inputDigest=digest)
            connection.execute(
                "INSERT INTO runtime_publication_heads VALUES(%s,%s,%s,%s,%s) "
                "ON CONFLICT(deployment_namespace,authority_issuer,namespace_id,definition_id) "
                "DO UPDATE SET revision=EXCLUDED.revision",
                (*key, expected + 1),
            )
            connection.execute(
                "INSERT INTO runtime_publication_receipts "
                "(deployment_namespace,actor,operation_id,payload_digest,result) "
                "VALUES(%s,%s,%s,%s,%s)",
                (key[0], trust.host_app_id, UUID(operation), digest, Jsonb(result)),
            )
            recheck()
            self.approvals._live(connection, trust)
            return result

    def _receipt(self, connection: Any, trust: HostManagementTrust, operation: str) -> Any:
        return connection.execute(
            "SELECT payload_digest,result FROM runtime_publication_receipts "
            "WHERE deployment_namespace=%s AND actor=%s AND operation_id=%s",
            (self.database.deployment_namespace, trust.host_app_id, UUID(operation)),
        ).fetchone()


def lock_definition(connection: Any, scope_key: tuple[str, str, Any]) -> None:
    """Serialize evaluation writes and publication for exactly one Definition."""
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("publication:" + repr(scope_key),)
    )
