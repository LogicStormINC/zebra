"""Internal release checks plus real database revocation/rotation acceptance."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.domain.extension_snapshots import (
    ExtensionPermissions,
    ExtensionSnapshot,
    ExtensionTaskCeiling,
    McpSnapshotEntry,
)
from agent_core.ports.extensions import ExtensionRevisionConflictError
from agent_security.extension_authority import extension_runtime_scope_from_grant
from agent_security.host_grant import HostGrantBindingError
from agent_security.mcp_credential_release import McpCredentialRelease
from agent_storage.postgres.extensions import PostgresExtensionStore

from tests.agent_security.test_extension_authority import _task_binding, _verified
from tests.agent_storage import test_mcp_credential_management as management_fixtures
from tests.agent_storage import test_postgres_mcp_credentials as fixtures

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
protector = fixtures.protector


def runtime(protector, *, store=None, connection=None):
    verified = _verified(scopes=["agent.run"])
    verified = replace(
        verified,
        context=verified.context.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(minutes=5)}
        ),
    )
    scope = extension_runtime_scope_from_grant(verified)
    record = fixtures.record(protector, scope=scope)
    if connection is None:
        from agent_core.domain.extensions import McpConnection

        connection = McpConnection(
            scope=scope,
            connection_id="mcp",
            revision=3,
            endpoint=record.binding.endpoint,
            enabled=True,
            auth_mode="bearer",
            auth_state="ready",
            credential_ref="credential",
        )
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id="session",
        turn_id="turn",
        mcp=(
            McpSnapshotEntry(
                connection=connection,
                catalog_digest="a" * 64,
                permissions=ExtensionPermissions(
                    tools=("search",), resources=("document",), prompts=("summary",)
                ),
            ),
        ),
    )
    snapshots = AsyncMock(get=AsyncMock(return_value=snapshot))
    tasks = Mock(
        resolve_task_ceiling=Mock(
            return_value=ExtensionTaskCeiling(task_id="task-a", binding=_task_binding(verified))
        )
    )
    store = store or AsyncMock(get_for_use=AsyncMock(return_value=record))
    service = McpCredentialRelease(store, snapshots, tasks, protector, "dev")
    args = dict(
        verified=verified,
        session_id="session",
        turn_id="turn",
        expected_digest=snapshot.digest,
        connection_id="mcp",
        endpoint=connection.endpoint,
        kind="tools",
        name="search",
    )
    return service, args, snapshot


@pytest.mark.parametrize(
    "kind,name", [("tools", "search"), ("resources", "document"), ("prompts", "summary")]
)
def test_permitted_release_is_secret_material_only(protector, kind, name):
    service, args, _ = runtime(protector)
    secret = asyncio.run(service.release(**(args | {"kind": kind, "name": name})))
    assert secret.value == fixtures.TOKEN
    assert fixtures.TOKEN not in repr(secret) + repr(service) + str(secret.redacted())


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "missing_expiry",
        "manage_only",
        "foreign",
        "digest",
        "turn",
        "connection",
        "kind",
        "name",
    ],
)
def test_authority_and_snapshot_reject_before_ciphertext_read(protector, change):
    service, args, _ = runtime(protector)
    verified = args["verified"]
    if change in ("expired", "missing_expiry"):
        args["verified"] = replace(
            verified,
            context=verified.context.model_copy(
                update={"expires_at": None if change == "missing_expiry" else datetime.now(UTC)}
            ),
        )
    elif change == "manage_only":
        args["verified"] = replace(
            verified, context=verified.context.model_copy(update={"scopes": ("extensions.manage",)})
        )
    elif change == "foreign":
        args["verified"] = replace(verified, subject_ref="other")
    else:
        args[
            {
                "digest": "expected_digest",
                "turn": "turn_id",
                "connection": "connection_id",
                "kind": "kind",
                "name": "name",
            }[change]
        ] = "wrong"
    with pytest.raises(HostGrantBindingError):
        asyncio.run(service.release(**args))
    service.store.get_for_use.assert_not_called()


def test_corrupt_binding_is_rejected_before_decryption(protector):
    service, args, _ = runtime(protector)
    service.store.get_for_use.return_value = fixtures.record(protector)
    with pytest.raises(HostGrantBindingError, match="credential binding mismatch"):
        asyncio.run(service.release(**args))


def test_grant_expiring_during_storage_wait_cannot_release(protector):
    service, args, _ = runtime(protector)
    from unittest.mock import patch

    from agent_security import mcp_credential_release as module

    first = datetime.now(UTC)
    with patch.object(module, "datetime") as clock:
        clock.now.side_effect = [first, first + timedelta(hours=1)]
        with pytest.raises(HostGrantBindingError, match="unexpired"):
            asyncio.run(service.release(**args))


def test_disabled_expected_configuration_fails_before_database_access(protector):
    from agent_storage.postgres.mcp_credentials import PostgresMcpCredentialStore

    _, _, snapshot = runtime(protector)
    connection = snapshot.mcp[0].connection.model_copy(update={"enabled": False})
    store = PostgresMcpCredentialStore("invalid-dsn", deployment_namespace="dev")
    from agent_core.ports.extensions import ExtensionNotFoundError

    with pytest.raises(ExtensionNotFoundError):
        asyncio.run(store.get_for_use(scope=snapshot.scope, expected_connection=connection))


@pytest.mark.parametrize("action", ["revoke", "rotate", "disable", "endpoint"])
def test_real_current_connection_invalidates_old_snapshot(dsn, protector, action):
    management, store, verified, scope = management_fixtures.management(dsn, protector)
    provisioned = asyncio.run(
        management.provision(
            verified=verified,
            connection_id="mcp",
            expected_connection_revision=1,
            token=fixtures.TOKEN,
        )
    )
    current = type(provisioned).model_validate(
        provisioned.model_dump() | {"enabled": True, "revision": 3}
    )
    configs = PostgresExtensionStore(dsn, deployment_namespace="dev")
    asyncio.run(configs.save_mcp(scope=scope, connection=current, expected_revision=2))
    service, args, _ = runtime(protector, store=store, connection=current)
    assert asyncio.run(service.release(**args)).value == fixtures.TOKEN
    if action == "revoke":
        asyncio.run(
            management.revoke(
                verified=verified, connection_id="mcp", expected_connection_revision=3
            )
        )
    elif action == "rotate":
        asyncio.run(
            management.provision(
                verified=verified,
                connection_id="mcp",
                expected_connection_revision=3,
                token="new-fixture-token",
            )
        )
    else:
        updates = (
            {"enabled": False}
            if action == "disable"
            else {"endpoint": "https://other.example.test/mcp"}
        )
        updated = type(current).model_validate(current.model_dump() | updates | {"revision": 4})
        asyncio.run(configs.save_mcp(scope=scope, connection=updated, expected_revision=3))
    with pytest.raises(ExtensionRevisionConflictError):
        asyncio.run(service.release(**args))
    # Historical reads remain possible but are not accepted by runtime release.
    assert (
        asyncio.run(
            store.get(scope=scope, connection_id="mcp", credential_ref=current.credential_ref)
        ).binding.credential_ref
        == current.credential_ref
    )
