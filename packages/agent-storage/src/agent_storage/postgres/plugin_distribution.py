"""Current distribution and immutable original receipts share one short transaction."""

import asyncio
from collections.abc import Callable
from time import monotonic
from typing import Any
from uuid import UUID

from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.plugin_distribution import PluginDistributionCommand
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.ports.extensions import ExtensionRevisionConflictError
from psycopg.types.json import Jsonb

from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementStore,
    HostManagementTrust,
)


def distribution_lock(
    connection: Any, namespace: str, digest: str, *, exclusive: bool = False
) -> None:
    # Shared checks; first management registration takes exclusive lock. No object IO.
    suffix = "" if exclusive else "_shared"
    connection.execute(
        f"SELECT pg_advisory_xact_lock{suffix}(hashtextextended(%s,0))",
        ("plugin-distribution:" + namespace + ":" + digest,),
    )


def distribution_in_transaction(
    connection: Any, namespace: str, scope: ExtensionScope, digest: str
) -> str | None:
    distribution_lock(connection, namespace, digest)
    managed = connection.execute(
        "SELECT 1 FROM plugin_managed_packages WHERE deployment_namespace=%s AND package_digest=%s",
        (namespace, digest),
    ).fetchone()
    if managed is None:
        return None
    row = connection.execute(
        "SELECT payload FROM plugin_product_distributions WHERE "
        "deployment_namespace=%s AND package_digest=%s AND scope_digest=%s FOR SHARE",
        (namespace, digest, json_digest(scope.model_dump(mode="json"))),
    ).fetchone()
    if (
        row is None
        or row["payload"].get("active") is not True
        or row["payload"].get("recipient") != scope.model_dump(mode="json")
    ):
        raise ExtensionRevisionConflictError("product distribution is unavailable")
    if not distribution_authority_current(connection, namespace, row["payload"]):
        raise ExtensionRevisionConflictError("product distribution approval changed")
    return json_digest(row["payload"])


def distribution_authority_current(
    connection: Any, namespace: str, payload: dict[str, Any]
) -> bool:
    authority = payload.get("authority", {})
    row = connection.execute(
        "SELECT revision,fingerprint,expires_at>clock_timestamp() AS live FROM "
        "host_management_approvals WHERE deployment_namespace=%s AND host_app_id=%s "
        "AND namespace_id=%s FOR SHARE",
        (namespace, authority.get("actor"), payload.get("scope", {}).get("namespace_id")),
    ).fetchone()
    return (
        row is not None
        and row["live"]
        and row["revision"] == authority.get("revision")
        and row["fingerprint"] == authority.get("fingerprint")
    )


class PluginDistributionStore:
    def __init__(self, dsn: str, namespace: str):
        self.approvals = HostManagementStore(dsn, deployment_namespace=namespace)
        self.namespace = namespace

    async def resolve(self, *, scope: ExtensionScope, package_digest: str) -> str | None:
        def read() -> str | None:
            with self.approvals._database.connect_task_io(deadline=monotonic() + 3) as connection:
                return distribution_in_transaction(
                    connection, self.namespace, scope, package_digest
                )

        return await asyncio.to_thread(read)

    def apply(
        self,
        trust: HostManagementTrust,
        command: PluginDistributionCommand,
        input_digest: str,
        recheck: Callable[[], None],
    ) -> dict[str, Any]:
        with self.approvals.authorized(trust) as connection:
            operation = (self.namespace, trust.host_app_id, UUID(command.operation_id))
            old = connection.execute(
                "SELECT payload_digest,result FROM runtime_publication_receipts WHERE "
                "deployment_namespace=%s AND actor=%s AND operation_id=%s",
                operation,
            ).fetchone()
            if old is not None:
                if (
                    old["payload_digest"] != input_digest
                    or old["result"].get("contractVersion") != "plugin-distribution/1"
                ):
                    raise HostManagementConflict("OPERATION_CONFLICT")
                return dict(old["result"])
            publication = connection.execute(
                "SELECT result FROM runtime_publication_receipts WHERE deployment_namespace=%s "
                "AND actor=%s AND operation_id=%s",
                (self.namespace, trust.host_app_id, UUID(command.publication_operation)),
            ).fetchone()
            if (
                publication is None
                or publication["result"].get("contractVersion") != "plugin-admission/1"
                or publication["result"].get("scope") != command.scope.model_dump(mode="json")
                or publication["result"].get("packageDigest") != command.package_digest
            ):
                raise HostManagementConflict("EXACT_PUBLICATION_REQUIRED")
            distribution_lock(connection, self.namespace, command.package_digest, exclusive=True)
            key = (
                self.namespace,
                command.package_digest,
                json_digest(command.recipient.model_dump(mode="json")),
            )
            row = connection.execute(
                "SELECT actor,revision,payload FROM plugin_product_distributions WHERE "
                "deployment_namespace=%s AND package_digest=%s AND scope_digest=%s FOR UPDATE",
                key,
            ).fetchone()
            if (
                (0 if row is None else row["revision"]) != command.expected_revision
                or row is not None
                and row["actor"] != trust.host_app_id
            ):
                raise HostManagementConflict("DISTRIBUTION_CAS")
            # A withdrawn generation never resurrects: regrant is another revision.
            result = {
                "contractVersion": "plugin-distribution/1",
                "scope": command.scope.model_dump(mode="json"),
                "recipient": command.recipient.model_dump(mode="json"),
                "packageDigest": command.package_digest,
                "publicationOperation": command.publication_operation,
                "operationId": command.operation_id,
                "inputDigest": input_digest,
                "revision": command.expected_revision + 1,
                "active": command.action == "distribute",
                "authority": {
                    "actor": trust.host_app_id,
                    "revision": trust.revision,
                    "fingerprint": trust.fingerprint,
                },
            }
            connection.execute(
                "INSERT INTO plugin_managed_packages VALUES(%s,%s) ON CONFLICT DO NOTHING", key[:2]
            )
            connection.execute(
                "INSERT INTO plugin_product_distributions VALUES(%s,%s,%s,%s,%s,%s) ON "
                "CONFLICT(deployment_namespace,package_digest,scope_digest) DO UPDATE SET "
                "revision=EXCLUDED.revision,payload=EXCLUDED.payload",
                (*key, trust.host_app_id, result["revision"], Jsonb(result)),
            )
            connection.execute(
                "INSERT INTO "
                "runtime_publication_receipts(deployment_namespace,actor,operation_id,payload_di"
                "gest,result) VALUES(%s,%s,%s,%s,%s)",
                (*operation, input_digest, Jsonb(result)),
            )
            recheck()
            self.approvals._live(connection, trust)
            return result

    def current(
        self, trust: HostManagementTrust, original: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self.approvals.authorized(trust) as connection:
            row = connection.execute(
                "SELECT payload FROM plugin_product_distributions WHERE "
                "deployment_namespace=%s AND package_digest=%s AND scope_digest=%s AND "
                "actor=%s FOR SHARE",
                (
                    self.namespace,
                    original["packageDigest"],
                    json_digest(original["recipient"]),
                    trust.host_app_id,
                ),
            ).fetchone()
            self.approvals._live(connection, trust)
            return (
                None
                if row is None
                else {
                    **dict(row["payload"]),
                    "effective": row["payload"].get("active") is True
                    and distribution_authority_current(connection, self.namespace, row["payload"]),
                }
            )
