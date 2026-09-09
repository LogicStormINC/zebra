import asyncio
from unittest.mock import AsyncMock

import pytest
from agent_core.application.mcp_connections import create_mcp_connection
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)
from pydantic import ValidationError

from tests.api.test_extension_reads import SCOPE

PAYLOAD = {"endpoint": "https://mcp.example/api"}


def test_creation_defaults_replay_after_toggle_and_mismatch() -> None:
    store = AsyncMock(spec=ExtensionStore)

    async def check() -> None:
        original, created = await create_mcp_connection(
            store=store, scope=SCOPE, idempotency_key="key", payload=PAYLOAD,
        )
        assert created and original.revision == 1 and not original.enabled
        assert original.auth_state == "not_required" and original.credential_ref is None
        store.save_mcp.side_effect = ExtensionRevisionConflictError()
        store.get_mcp_creation.return_value = original
        current = original.model_copy(update={"enabled": True, "revision": 2})
        store.get_mcp.return_value = current
        replay, created = await create_mcp_connection(
            store=store, scope=SCOPE, idempotency_key="key",
            payload=PAYLOAD | {"transport": "streamable_http", "auth_mode": "none"},
        )
        assert replay == current and not created
        assert all(call.kwargs["expected_revision"] is None
                   for call in store.save_mcp.await_args_list)
        with pytest.raises(ExtensionRevisionConflictError):
            await create_mcp_connection(
                store=store, scope=SCOPE, idempotency_key="key",
                payload=PAYLOAD | {"auth_mode": "bearer"},
            )

    asyncio.run(check())


@pytest.mark.parametrize("mode", ["bearer", "api_key", "oauth"])
def test_pending_auth(mode: str) -> None:
    record, created = asyncio.run(create_mcp_connection(
        store=AsyncMock(spec=ExtensionStore), scope=SCOPE, idempotency_key="k",
        payload=PAYLOAD | {"auth_mode": mode},
    ))
    assert created and record.auth_state == "pending" and record.credential_ref is None
    assert not record.enabled


@pytest.mark.parametrize("key", ["", "x" * 129, "has space", "\n", "\x7f", "é", 3, None])
def test_invalid_key_before_storage(key: object) -> None:
    store = AsyncMock(spec=ExtensionStore)
    with pytest.raises(ValidationError):
        asyncio.run(create_mcp_connection(
            store=store, scope=SCOPE, idempotency_key=key, payload=PAYLOAD,  # type: ignore[arg-type]
        ))
    assert not store.mock_calls


@pytest.mark.parametrize("getter", ["get_mcp_creation", "get_mcp"])
@pytest.mark.parametrize("drift", ["scope", "connection_id", "type", "revision"])
def test_adapter_identity_fails_closed(getter: str, drift: str) -> None:
    store = AsyncMock(spec=ExtensionStore)
    original, _ = asyncio.run(create_mcp_connection(
        store=store, scope=SCOPE, idempotency_key="key", payload=PAYLOAD,
    ))
    store.save_mcp.side_effect = ExtensionRevisionConflictError()
    store.get_mcp_creation.return_value = original
    store.get_mcp.return_value = original
    bad = (None if drift == "type" else original.model_copy(update={
        drift: {"scope": SCOPE.model_copy(update={"principal_id": "other"}),
                "connection_id": "other", "revision": 0}[drift],
    }))
    getattr(store, getter).return_value = bad
    with pytest.raises(RuntimeError if drift == "revision" else ExtensionNotFoundError):
        asyncio.run(create_mcp_connection(
            store=store, scope=SCOPE, idempotency_key="key", payload=PAYLOAD,
        ))


@pytest.mark.parametrize("operation", ["save_mcp", "get_mcp_creation", "get_mcp"])
def test_store_validation_error_is_server_failure(operation: str) -> None:
    store = AsyncMock(spec=ExtensionStore)
    original, _ = asyncio.run(create_mcp_connection(
        store=store, scope=SCOPE, idempotency_key="key", payload=PAYLOAD,
    ))
    store.save_mcp.side_effect = ExtensionRevisionConflictError()
    store.get_mcp_creation.return_value = original
    store.get_mcp.return_value = original
    getattr(store, operation).side_effect = ValidationError.from_exception_data("secret", [])
    with pytest.raises(RuntimeError, match="Invalid persisted extension configuration"):
        asyncio.run(create_mcp_connection(
            store=store, scope=SCOPE, idempotency_key="key", payload=PAYLOAD,
        ))
