"""Plugin publication receipts reuse v111 immutable operations, not Definition heads."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementStore,
    HostManagementTrust,
)


class PluginAdmissionStore:
    def __init__(self, dsn: str, namespace: str) -> None:
        self.approvals = HostManagementStore(dsn, deployment_namespace=namespace)
        self.namespace = namespace

    def read(
        self, trust: HostManagementTrust, operation: str | None = None
    ) -> dict[str, Any] | None:
        with self.approvals.authorized(trust) as connection:
            row = (
                None
                if operation is None
                else connection.execute(
                    "SELECT result FROM runtime_publication_receipts "
                    "WHERE deployment_namespace=%s AND actor=%s AND operation_id=%s",
                    (self.namespace, trust.host_app_id, UUID(operation)),
                ).fetchone()
            )
            self.approvals._live(connection, trust)
            return None if row is None else dict(row["result"])

    def record(
        self,
        trust: HostManagementTrust,
        operation: str,
        digest: str,
        result: dict[str, Any],
        recheck: Callable[[], None],
    ) -> dict[str, Any]:
        # Object publication happens BEFORE this short metadata transaction. A rejected
        # commit may leave an unreferenced immutable object, never an installation.
        with self.approvals.authorized(trust) as connection:
            key = (self.namespace, trust.host_app_id, UUID(operation))
            row = connection.execute(
                "SELECT payload_digest,result FROM runtime_publication_receipts "
                "WHERE deployment_namespace=%s AND actor=%s AND operation_id=%s",
                key,
            ).fetchone()
            if row is not None:
                if row["payload_digest"] != digest:
                    raise HostManagementConflict("OPERATION_CONFLICT")
                recheck()
                self.approvals._live(connection, trust)
                return dict(row["result"])
            connection.execute(
                "INSERT INTO runtime_publication_receipts "
                "(deployment_namespace,actor,operation_id,payload_digest,result) "
                "VALUES(%s,%s,%s,%s,%s)",
                (*key, digest, Jsonb(result)),
            )
            recheck()
            self.approvals._live(connection, trust)
            return result
