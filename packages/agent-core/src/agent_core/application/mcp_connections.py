"""Idempotent configuration creation; no endpoint or credential I/O."""

from collections.abc import Callable
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from agent_core.domain.extensions import (
    ExtensionIdempotencyKey,
    ExtensionScope,
    McpAuthMode,
    McpAuthState,
    McpConnection,
)
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)

_KEY: TypeAdapter[str] = TypeAdapter(ExtensionIdempotencyKey)


class McpConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: str = Field(strict=True, max_length=2048)
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    auth_mode: McpAuthMode = McpAuthMode.NONE


def _checked(record: McpConnection, expected: McpConnection) -> McpConnection:
    if (not isinstance(record, McpConnection) or record.scope != expected.scope
            or record.connection_id != expected.connection_id):
        raise ExtensionNotFoundError("Extension configuration was not found")
    return McpConnection.model_validate(record.model_dump())


async def create_mcp_connection(
    *, store: ExtensionStore, scope: ExtensionScope, idempotency_key: str,
    payload: object,
    before_save: Callable[[], None] | None = None,
) -> tuple[McpConnection, bool]:
    key = _KEY.validate_python(idempotency_key)
    request = McpConnectionCreate.model_validate(payload)
    scope = ExtensionScope.model_validate(scope.model_dump())
    connection = McpConnection(
        scope=scope, connection_id="mcp_" + sha256(
            b"zebra:mcp-connection:create:v1\0" + key.encode("ascii")
        ).hexdigest(), revision=1, enabled=False,
        endpoint=request.endpoint, transport=request.transport, auth_mode=request.auth_mode,
        auth_state=(McpAuthState.NOT_REQUIRED if request.auth_mode == McpAuthMode.NONE
                    else McpAuthState.PENDING),
    )
    try:
        try:
            if before_save is not None:
                before_save()
            await store.save_mcp(scope=scope, connection=connection, expected_revision=None)
        except ExtensionRevisionConflictError:
            original = _checked(await store.get_mcp_creation(
                scope=scope, connection_id=connection.connection_id,
            ), connection)
            if original.revision != 1:
                raise ExtensionNotFoundError("Extension creation was not found") from None
            if original != connection:
                raise ExtensionRevisionConflictError("Idempotency key request differs") from None
            current = _checked(await store.get_mcp(
                scope=scope, connection_id=connection.connection_id,
            ), connection)
            return current, False
    except ValidationError:
        raise RuntimeError("Invalid persisted extension configuration") from None
    return connection, True
