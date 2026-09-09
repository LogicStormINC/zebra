"""Append-only catalog publication serialized with connection configuration changes."""

import asyncio

from agent_core.domain.extensions import (
    ExtensionDigest,
    ExtensionRevision,
    ExtensionScope,
    OpaqueExtensionId,
)
from agent_core.domain.mcp_catalog import McpToolCatalog
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.extensions import _COLUMNS, _KEY, _scope_key
from agent_storage.postgres.mcp_credentials import _locked_connection


class PostgresMcpCatalogStore(PostgresDatabase):
    async def publish(self, *, scope: ExtensionScope, catalog: McpToolCatalog) -> None:
        catalog = McpToolCatalog.model_validate(catalog.model_dump())
        if catalog.connection.scope != scope:
            raise ValueError("MCP catalog scope mismatch")
        await asyncio.to_thread(self._publish, scope, catalog)

    def _publish(self, scope: ExtensionScope, catalog: McpToolCatalog) -> None:
        key = (
            *_scope_key(self.deployment_namespace, scope, "mcp"),
            catalog.connection.connection_id,
        )
        with self.connect() as transaction:
            current = _locked_connection(transaction, key, scope)
            if current != catalog.connection:
                raise ExtensionRevisionConflictError(
                    "MCP catalog connection changed during discovery"
                )
            transaction.execute(
                "INSERT INTO mcp_catalog_versions (" + _COLUMNS + ", revision, digest, payload) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (scope_digest, kind, object_id, revision, digest) DO UPDATE "
                "SET publication_sequence=EXCLUDED.publication_sequence "
                "WHERE mcp_catalog_versions.payload=EXCLUDED.payload",
                (*key, current.revision, catalog.digest, Jsonb(catalog.model_dump(mode="json"))),
            )
            row = transaction.execute(
                "SELECT payload FROM mcp_catalog_versions WHERE "
                + _KEY
                + " AND revision=%s AND digest=%s",
                (*key, current.revision, catalog.digest),
            ).fetchone()
            if row is None or row["payload"] != catalog.model_dump(mode="json"):
                raise McpCatalogIntegrityError("MCP catalog publication integrity failure")

    async def get(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
        config_revision: int,
        expected_digest: str,
    ) -> McpToolCatalog:
        TypeAdapter(ExtensionDigest).validate_python(expected_digest)
        return await asyncio.to_thread(
            self._read, scope, connection_id, config_revision, expected_digest
        )

    async def latest(
        self, *, scope: ExtensionScope, connection_id: str, config_revision: int
    ) -> McpToolCatalog:
        return await asyncio.to_thread(self._read, scope, connection_id, config_revision, None)

    def _read(
        self, scope: ExtensionScope, connection_id: str, revision: int, expected: str | None
    ) -> McpToolCatalog:
        TypeAdapter(OpaqueExtensionId).validate_python(connection_id)
        TypeAdapter(ExtensionRevision).validate_python(revision)
        key = (*_scope_key(self.deployment_namespace, scope, "mcp"), connection_id, revision)
        condition = (
            " AND digest=%s"
            if expected is not None
            else " ORDER BY publication_sequence DESC LIMIT 1"
        )
        with self.connect() as transaction:
            row = transaction.execute(
                "SELECT digest, payload FROM mcp_catalog_versions WHERE "
                + _KEY
                + " AND revision=%s"
                + condition,
                (*key, expected) if expected is not None else key,
            ).fetchone()
        if row is None:
            raise ExtensionNotFoundError("MCP catalog unavailable")
        try:
            catalog = McpToolCatalog.model_validate(row["payload"])
            if (
                catalog.connection.scope != scope
                or catalog.connection.connection_id != connection_id
                or catalog.connection.revision != revision
                or catalog.digest != row["digest"]
                or (expected is not None and catalog.digest != expected)
            ):
                raise ValueError
            return catalog
        except ValueError:
            raise McpCatalogIntegrityError("MCP catalog integrity failure") from None
