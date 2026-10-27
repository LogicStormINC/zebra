"""Real PG product distribution -> installer -> frozen Worker guard -> withdrawal."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.plugin_distribution import PluginDistributionCommand
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.ports.extensions import ExtensionRevisionConflictError
from agent_storage.postgres.plugin_distribution import (
    PluginDistributionStore,
)
from fastapi.testclient import TestClient
from zebra_agent_api.plugin_distribution import HEADER, PATH, plugin_distribution_contract

from tests.agent_storage.test_host_management import host_management_dsn  # noqa: F401
from tests.api.test_plugin_admission import admitted, publication  # noqa: F401


def command(p, op, **changes):
    return {
        "action": "distribute",
        "scope": p.approval["scope"],
        "recipient": {
            "authority_issuer": p.approval["scope"]["authority_issuer"],
            "namespace_id": "local",
            "principal_id": "business-user",
            "workspace_id": "workspace",
        },
        "publication_operation": op,
        "operation_id": str(uuid4()),
        "expected_revision": 0,
        "package_digest": p.package.package_digest,
        **changes,
    }


def test_distribution_shared_cas_original_get_and_generation(admitted):  # noqa: F811
    p = admitted
    with TestClient(p.app) as client:
        pub = publication(p)
        assert (
            client.post("/management/v1/plugin-admission", headers=p.headers, json=pub).status_code
            == 200
        )
        h = {**p.headers, HEADER: plugin_distribution_contract()["contractDigest"]}
        h.pop("x-runtime-plugin-contract")
        c = command(p, pub["operation_id"])
        store = PluginDistributionStore(p.cfg.database_url, "local")
        scope = ExtensionScope.model_validate(c["recipient"])
        with pytest.raises(ExtensionRevisionConflictError):
            asyncio.run(store.resolve(scope=scope, package_digest=p.package.package_digest))

        def submit(_):
            with TestClient(p.app) as replica:
                return replica.post(PATH, headers=h, json=c)

        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(submit, range(2)))
        assert [r.status_code for r in responses] == [200, 200]
        from pathlib import Path

        from agent_core.application.plugin_catalog import plugin_catalog
        from agent_core.ports.extensions import ExtensionPageRequest
        from agent_integrations.plugins.publication import PluginPackagePublicationService

        publisher = PluginPackagePublicationService(
            Path(p.cfg.plugins.bundle_root), (p.package.package_digest,), p.objects, "local"
        )
        catalog = asyncio.run(
            plugin_catalog(publisher, store, scope, ExtensionPageRequest(limit=1))
        )
        assert len(catalog.items) == 1
        original = responses[0].json()["originalResult"]
        generation = asyncio.run(
            store.resolve(scope=scope, package_digest=p.package.package_digest)
        )
        assert generation == json_digest(original)
        wrong = scope.model_copy(update={"principal_id": "different"})
        with pytest.raises(ExtensionRevisionConflictError):
            asyncio.run(store.resolve(scope=wrong, package_digest=p.package.package_digest))
        hidden = asyncio.run(plugin_catalog(publisher, store, wrong, ExtensionPageRequest(limit=1)))
        assert hidden.items == () and hidden.next_cursor is None
        changed = {**c, "expected_revision": 1}
        assert client.post(PATH, headers=h, json=changed).status_code == 409
        withdraw = command(p, pub["operation_id"], action="withdraw", expected_revision=1)
        response = client.post(PATH, headers=h, json=withdraw)
        assert response.status_code == 200, response.text
        with pytest.raises(ExtensionRevisionConflictError):
            asyncio.run(store.resolve(scope=scope, package_digest=p.package.package_digest))
        observed = client.get(PATH, headers={**h, "x-runtime-operation": c["operation_id"]}).json()
        assert observed["originalResult"] == original
        assert observed["currentDistribution"]["active"] is False
        new = command(p, pub["operation_id"], expected_revision=2)
        assert client.post(PATH, headers=h, json=new).status_code == 200
        assert (
            asyncio.run(store.resolve(scope=scope, package_digest=p.package.package_digest))
            != generation
        )
        assert (
            client.get(PATH, headers={**h, "x-runtime-operation": str(uuid4())}).status_code == 404
        )
        assert client.get(PATH + "?retry=1", headers=h).status_code == 400
        assert client.request("GET", PATH, headers=h, json={}).status_code == 400
        assert (
            client.post(
                PATH,
                headers=h,
                json={**c, "recipient": {**c["recipient"], "namespace_id": "other"}},
            ).status_code
            == 422
        )


def test_managed_package_cannot_enable_old_generation_or_legacy_installation(admitted):  # noqa: F811
    from agent_core.domain.extension_snapshots import ExtensionSnapshot, McpSnapshotEntry
    from agent_core.domain.plugin_snapshots import PluginSnapshot
    from agent_storage.postgres.extensions import (
        PostgresExtensionStore,
    )
    from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
    from agent_storage.postgres.plugin_admission import validate_plugin_snapshot_in_transaction
    from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore

    from tests.agent_storage.test_postgres_plugin_installations import _catalog, _record

    p = admitted
    # Use an existing real MCP fixture, but publish that exact pin as a separate original.
    record = _record()
    scope = record.scope.model_copy(
        update={
            "authority_issuer": p.approval["scope"]["authority_issuer"],
            "namespace_id": "local",
        }
    )
    pin = record.package
    expectation = pin.expectation.model_copy(update={"deployment_namespace": "local"})
    pin = pin.model_copy(
        update={
            "expectation": expectation,
            "receipt": pin.receipt.model_copy(update={"expectation": expectation}),
        }
    )
    connection = record.bindings[0].connection.model_copy(update={"scope": scope})
    catalog = _catalog(connection)
    binding = record.bindings[0].model_copy(
        update={"connection": connection, "catalog_digest": catalog.digest}
    )
    record = record.model_copy(update={"scope": scope, "package": pin, "bindings": (binding,)})
    store = PluginDistributionStore(p.cfg.database_url, "local")
    from agent_storage.postgres.plugin_publication_receipts import PluginAdmissionStore
    from zebra_agent_api.plugin_admission_config import load_plugin_approval

    approval = load_plugin_approval(str(p.path), "local")
    pub = str(uuid4())
    PluginAdmissionStore(p.cfg.database_url, "local").record(
        approval.trust,
        pub,
        "a" * 64,
        {
            "contractVersion": "plugin-admission/1",
            "scope": approval.scope.model_dump(mode="json"),
            "packageDigest": pin.package_digest,
            "pin": pin.model_dump(mode="json"),
        },
        lambda: None,
    )
    cmd = PluginDistributionCommand.model_validate(
        command(p, pub, recipient=scope.model_dump(), package_digest=pin.package_digest)
    )
    grant = store.apply(approval.trust, cmd, json_digest(cmd.model_dump(mode="json")), lambda: None)
    installs = PostgresPluginInstallationStore(p.cfg.database_url, deployment_namespace="local")

    async def seed():
        await PostgresExtensionStore(p.cfg.database_url, deployment_namespace="local").save_mcp(
            scope=scope, connection=connection, expected_revision=None
        )
        await PostgresMcpCatalogStore(p.cfg.database_url, deployment_namespace="local").publish(
            scope=scope, catalog=catalog
        )
        with pytest.raises(ExtensionRevisionConflictError):
            await installs.save(scope=scope, installation=record, expected_revision=None)
        current = record.model_copy(update={"distribution_digest": json_digest(grant)})
        await installs.save(scope=scope, installation=current, expected_revision=None)
        current = current.model_copy(update={"revision": 2, "enabled": True})
        await installs.save(scope=scope, installation=current, expected_revision=1)
        return current

    record = asyncio.run(seed())
    entry = McpSnapshotEntry(connection=connection, catalog_digest=catalog.digest)
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id="session",
        turn_id="turn",
        mcp=(entry,),
        plugins=(PluginSnapshot.from_installation(record),),
    )
    with installs.connect() as sql:
        validate_plugin_snapshot_in_transaction(sql, installs, snapshot)
    from types import SimpleNamespace

    from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
    from zebra_agent_worker.worker_plugins import WorkerPluginGuard, WorkerPluginSource

    guard = WorkerPluginGuard(
        WorkerPluginSource(installs, None),
        SimpleNamespace(scope=scope, snapshot=snapshot),
        (record,),
    )
    guard.validate()
    # Exact immutable facts remain available after shared withdrawal; current batch rejects.
    withdrawn = cmd.model_copy(
        update={"action": "withdraw", "expected_revision": 1, "operation_id": str(uuid4())}
    )
    store.apply(
        approval.trust, withdrawn, json_digest(withdrawn.model_dump(mode="json")), lambda: None
    )
    assert (
        asyncio.run(
            installs.get_current_batch(scope=scope, installation_ids=(record.installation_id,))
        )
        == ()
    )
    assert (
        asyncio.run(
            installs.get_revision(scope=scope, installation_id=record.installation_id, revision=2)
        )
        == record
    )
    with pytest.raises(PluginAuthorityUnavailable):
        guard.validate()
    from agent_storage.postgres.extensions import ExtensionSnapshotAdmissionConflictError

    with installs.connect() as sql, pytest.raises(ExtensionSnapshotAdmissionConflictError):
        validate_plugin_snapshot_in_transaction(sql, installs, snapshot)
    renewed = cmd.model_copy(update={"expected_revision": 2, "operation_id": str(uuid4())})
    store.apply(approval.trust, renewed, json_digest(renewed.model_dump(mode="json")), lambda: None)
    assert (
        asyncio.run(
            installs.get_current_batch(scope=scope, installation_ids=(record.installation_id,))
        )
        == ()
    )
