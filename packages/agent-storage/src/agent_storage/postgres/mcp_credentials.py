"""Encrypted storage only: Broker must separately authorize use and revocation."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from typing import Any

import psycopg
from agent_core.domain.extensions import ExtensionScope, McpConnection, OpaqueExtensionId
from agent_core.domain.mcp_credentials import (
    McpCredentialBinding,
    SealedMcpCredential,
    StoredMcpCredential,
)
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.extensions import (
    _COLUMNS,
    _CURRENT,
    _KEY,
    PostgresExtensionStore,
    _decode_record,
    _scope_key,
)

_WHERE = """key_digest = %s AND scope_digest = %s AND deployment_namespace = %s
    AND authority_issuer = %s AND namespace_id = %s AND principal_id = %s
    AND workspace_id = %s AND kind = %s AND object_id = %s AND credential_ref = %s"""
_IDENTIFIER = TypeAdapter(OpaqueExtensionId)


class PostgresMcpCredentialStore(PostgresDatabase):
    async def save(
        self,
        *,
        scope: ExtensionScope,
        record: StoredMcpCredential,
        expected_revision: int | None,
    ) -> None:
        binding, envelope = self._validate_record(scope, record, expected_revision)
        await asyncio.to_thread(self._save, binding, envelope, expected_revision)

    def _validate_record(
        self,
        scope: ExtensionScope,
        record: StoredMcpCredential,
        expected_revision: int | None,
    ) -> tuple[McpCredentialBinding, SealedMcpCredential]:
        binding = McpCredentialBinding.model_validate(record.binding.model_dump())
        if binding.scope != scope or binding.deployment_namespace != self.deployment_namespace:
            raise ValueError("credential storage scope mismatch")
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise ValueError("invalid expected credential revision")
        if binding.credential_revision != (expected_revision or 0) + 1:
            raise ValueError("credential revision must advance by one")
        # Validate the envelope before any database I/O, including reconstructed records.
        envelope = SealedMcpCredential(
            record.envelope.key_handle,
            record.envelope.key_version,
            record.envelope.nonce,
            record.envelope.ciphertext,
        )
        return binding, envelope

    async def get_connection(self, *, scope: ExtensionScope, connection_id: str) -> McpConnection:
        _IDENTIFIER.validate_python(connection_id)
        return await PostgresExtensionStore(
            self._dsn,
            deployment_namespace=self.deployment_namespace,
        ).get_mcp(scope=scope, connection_id=connection_id)

    async def publish(
        self,
        *,
        scope: ExtensionScope,
        record: StoredMcpCredential,
        expected_connection_revision: int,
    ) -> McpConnection:
        _require_revision(expected_connection_revision)
        binding, envelope = self._validate_record(scope, record, None)
        result = await asyncio.to_thread(
            self._save,
            binding,
            envelope,
            None,
            expected_connection_revision,
        )
        assert result is not None
        return result

    async def revoke(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
        expected_connection_revision: int,
    ) -> McpConnection:
        _require_revision(expected_connection_revision)
        _IDENTIFIER.validate_python(connection_id)
        return await asyncio.to_thread(
            self._revoke, scope, connection_id, expected_connection_revision
        )

    def _revoke(self, scope: ExtensionScope, connection_id: str, expected: int) -> McpConnection:
        key = (*_scope_key(self.deployment_namespace, scope, "mcp"), connection_id)
        with self.connect() as transaction:
            current = _locked_connection(transaction, key, scope)
            if current.revision != expected:
                raise ExtensionRevisionConflictError("MCP connection revision conflict")
            if current.auth_mode.value == "none":
                raise ValueError("MCP connection has no credential authentication")
            updated = McpConnection.model_validate(
                current.model_dump()
                | {
                    "revision": current.revision + 1,
                    "enabled": False,
                    "auth_state": "revoked",
                }
            )
            _write_connection(transaction, key, updated)
            return updated

    def _save(
        self,
        binding: McpCredentialBinding,
        envelope: SealedMcpCredential,
        expected_revision: int | None,
        expected_connection_revision: int | None = None,
    ) -> McpConnection | None:
        coordinates = _scope_key(self.deployment_namespace, binding.scope, "mcp")
        key = self._key(binding.scope, binding.connection_id, binding.credential_ref)
        with self.connect() as connection:
            # Parent lock serializes credential creation/rotation and config updates.
            current = _locked_connection(
                connection, (*coordinates, binding.connection_id), binding.scope
            )
            if (
                expected_connection_revision is not None
                and current.revision != expected_connection_revision
            ):
                raise ExtensionRevisionConflictError("MCP connection revision conflict")
            if current.endpoint != binding.endpoint or current.auth_mode.value != binding.auth_mode:
                raise ExtensionRevisionConflictError("MCP connection binding changed")
            latest = connection.execute(
                "SELECT revision FROM mcp_credential_versions WHERE "
                + _WHERE
                + " ORDER BY revision DESC LIMIT 1",
                key,
            ).fetchone()
            if (latest["revision"] if latest else None) != expected_revision:
                raise ExtensionRevisionConflictError("credential revision conflict")
            connection.execute(
                """INSERT INTO mcp_credential_versions (
                    key_digest, scope_digest, deployment_namespace, authority_issuer,
                    namespace_id, principal_id, workspace_id, kind, object_id, credential_ref,
                    revision, binding, key_handle, key_version, nonce, ciphertext
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    *key,
                    binding.credential_revision,
                    Jsonb(binding.model_dump(mode="json")),
                    envelope.key_handle,
                    envelope.key_version,
                    envelope.nonce,
                    envelope.ciphertext,
                ),
            )
            if expected_connection_revision is not None:
                updated = McpConnection.model_validate(
                    current.model_dump()
                    | {
                        "revision": current.revision + 1,
                        "credential_ref": binding.credential_ref,
                        "auth_state": "ready",
                    }
                )
                _write_connection(connection, (*coordinates, binding.connection_id), updated)
                return updated
        return None

    async def get(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
        credential_ref: str,
        revision: int | None = None,
    ) -> StoredMcpCredential:
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("invalid credential revision")
        return await asyncio.to_thread(self._get, scope, connection_id, credential_ref, revision)

    async def get_for_use(
        self, *, scope: ExtensionScope, expected_connection: McpConnection
    ) -> StoredMcpCredential:
        if (
            expected_connection.scope != scope
            or not expected_connection.enabled
            or expected_connection.auth_state.value != "ready"
            or expected_connection.auth_mode.value not in ("bearer", "api_key")
            or expected_connection.credential_ref is None
        ):
            raise ExtensionNotFoundError("MCP credential unavailable for use")
        return await asyncio.to_thread(self._get_for_use, scope, expected_connection)

    def _get_for_use(self, scope: ExtensionScope, expected: McpConnection) -> StoredMcpCredential:
        key = (*_scope_key(self.deployment_namespace, scope, "mcp"), expected.connection_id)
        with self.connect() as connection:
            current = _locked_connection(connection, key, scope)
            if current != expected:
                raise ExtensionRevisionConflictError("MCP connection changed before credential use")
            assert current.credential_ref is not None
            # Management publication pins a fresh reference at revision 1, never latest history.
            return self._read(connection, scope, current.connection_id, current.credential_ref, 1)

    def _get(
        self,
        scope: ExtensionScope,
        connection_id: str,
        credential_ref: str,
        revision: int | None,
    ) -> StoredMcpCredential:
        with self.connect() as connection:
            return self._read(connection, scope, connection_id, credential_ref, revision)

    def _read(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        scope: ExtensionScope,
        connection_id: str,
        credential_ref: str,
        revision: int | None,
    ) -> StoredMcpCredential:
        key = self._key(scope, connection_id, credential_ref)
        row = connection.execute(
            "SELECT * FROM mcp_credential_versions WHERE "
            + _WHERE
            + (" AND revision = %s" if revision is not None else "")
            + " ORDER BY revision DESC LIMIT 1",
            (*key, revision) if revision is not None else key,
        ).fetchone()
        if row is None:
            raise ExtensionNotFoundError("credential unavailable")
        binding = McpCredentialBinding.model_validate(row["binding"])
        if (
            binding.scope != scope
            or binding.deployment_namespace != self.deployment_namespace
            or binding.connection_id != connection_id
            or binding.credential_ref != credential_ref
            or binding.credential_revision != row["revision"]
        ):
            raise ValueError("credential payload disagrees with storage coordinates")
        return StoredMcpCredential(
            binding,
            SealedMcpCredential(
                row["key_handle"],
                row["key_version"],
                bytes(row["nonce"]),
                bytes(row["ciphertext"]),
            ),
        )

    def _key(
        self, scope: ExtensionScope, connection_id: str, credential_ref: str
    ) -> tuple[str, ...]:
        connection_id = _IDENTIFIER.validate_python(connection_id)
        credential_ref = _IDENTIFIER.validate_python(credential_ref)
        coordinates = (
            *_scope_key(self.deployment_namespace, scope, "mcp"),
            connection_id,
            credential_ref,
        )
        digest = sha256(json.dumps(coordinates, ensure_ascii=True).encode()).hexdigest()
        return (digest, *coordinates)


def _locked_connection(
    transaction: psycopg.Connection[dict[str, Any]],
    key: tuple[str, ...],
    scope: ExtensionScope,
) -> McpConnection:
    parent = transaction.execute(
        "SELECT revision FROM extension_configurations WHERE " + _KEY + " FOR UPDATE", key
    ).fetchone()
    if parent is None:
        raise ExtensionNotFoundError("MCP connection unavailable")
    # Read in a fresh statement after the lock: a waiting join can retain a stale revision.
    row = transaction.execute(_CURRENT + _KEY, key).fetchone()
    if row is None:
        raise ValueError("MCP configuration revision is missing")
    return _decode_record(McpConnection, row, scope)


def _require_revision(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("invalid expected connection revision")


def _write_connection(
    transaction: psycopg.Connection[dict[str, Any]],
    key: tuple[str, ...],
    updated: McpConnection,
) -> None:
    # Caller holds the exact parent lock; ciphertext and projection share this transaction.
    transaction.execute(
        "INSERT INTO extension_configuration_revisions (" + _COLUMNS + ", revision, payload) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (*key, updated.revision, Jsonb(updated.model_dump(mode="json"))),
    )
    transaction.execute(
        "UPDATE extension_configurations SET revision = %s WHERE " + _KEY,
        (updated.revision, *key),
    )
