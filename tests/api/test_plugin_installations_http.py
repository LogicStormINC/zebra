"""Default-off plugin HTTP surface and bounded Host Grant protected mutations."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agent_core.ports.plugin_installations import PluginInstallationPage
from agent_security.extension_authority import extension_scope_from_grant
from agent_storage import sqlite_control_plane_stores
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_config.plugin_settings import PluginSettings

from tests.agent_security.test_extension_authority import _verified
from tests.agent_storage.test_postgres_plugin_installations import _record
from tests.api.test_extension_reads import AUTH, Authorizer
from tests.api.test_host_auth_http import _cloud_settings, _local_settings

PREFIX = "/v1/extensions/plugin-installations"


def _client(
    tmp_path: Path, *, enabled: bool = True, local: bool = False, scopes: list[str] | None = None
) -> tuple[TestClient, AsyncMock]:
    verified = _verified(
        scopes=scopes if scopes is not None else ["extensions.read", "extensions.manage"]
    )
    scope = extension_scope_from_grant(_verified(), permission="extensions.read")
    record = _record()
    values = record.model_dump()
    values["scope"] = scope
    values["bindings"][0]["connection"]["scope"] = scope
    record = type(record).model_validate(values)
    service = AsyncMock()
    service.install.return_value = (record, True)
    service.store.get.return_value = record
    service.store.list.return_value = PluginInstallationPage(items=(record,))
    service.update.return_value = record.model_copy(update={"revision": 2, "enabled": True})
    settings = _local_settings() if local else _cloud_settings("postgresql://unused/zebra")
    settings = replace(
        settings,
        plugins=PluginSettings(enabled=enabled),
        cloud_extensions_read_enabled=True,
        cloud_extensions_manage_enabled=True,
    )
    database = tmp_path / "plugins.sqlite"
    return TestClient(
        create_http_app(
            database,
            settings=settings,
            stores=sqlite_control_plane_stores(database),
            extension_store=AsyncMock(),
            host_grant_authorizer=Authorizer(verified),
            plugin_installation_service=service,
        )
    ), service


@pytest.mark.parametrize("local,enabled", [(False, False), (True, True)])
def test_default_off_or_local_has_no_plugin_io(tmp_path: Path, local: bool, enabled: bool) -> None:
    client, service = _client(tmp_path, enabled=enabled, local=local)
    for method in ("get", "post", "patch"):
        assert getattr(client, method)(PREFIX, headers=AUTH).status_code == 404
    assert not service.mock_calls


def test_plugin_crud_redacts_private_facts_and_requires_cas(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    listing = client.get(PREFIX, headers=AUTH)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["enabled"] is False
    detail = client.get(PREFIX + "/plugin-a", headers=AUTH)
    assert detail.headers["etag"] == '"1"'
    payload = {
        "package_digest": service.store.get.return_value.package.package_digest,
        "bindings": [
            {
                "component_id": "test-mcp",
                "kind": "mcp-http",
                "connection_id": "connection-a",
            }
        ],
    }
    created = client.post(PREFIX, headers=AUTH | {"Idempotency-Key": "one"}, json=payload)
    assert created.status_code == 201
    assert created.headers["location"] == PREFIX + "/plugin-a"
    assert service.install.call_args.kwargs["operated_by"] == _verified().subject_ref
    assert (
        client.patch(PREFIX + "/plugin-a", headers=AUTH, json={"enabled": True}).status_code == 428
    )
    updated = client.patch(
        PREFIX + "/plugin-a", headers=AUTH | {"If-Match": '"1"'}, json={"enabled": True}
    )
    assert updated.status_code == 200 and updated.headers["etag"] == '"2"'
    for result in (listing, detail, created, updated):
        assert result.headers["cache-control"] == "no-store"
        for secret in (
            "credential_ref",
            "canonical_manifest",
            "object_version",
            "artifact_id",
            '"scope"',
        ):
            assert secret not in result.text
    for invalid in ({**payload, "bundle_root": "/tmp/evil"}, {"receipt": {}}, {"enabled": True}):
        assert (
            client.post(PREFIX, headers=AUTH | {"Idempotency-Key": "two"}, json=invalid).status_code
            == 422
        )
    assert client.get(PREFIX + "?limit=101", headers=AUTH).status_code == 422
    assert client.get(PREFIX + "?limit=1&limit=2", headers=AUTH).status_code == 422
    assert (
        client.post(
            PREFIX, headers=AUTH | {"Idempotency-Key": "two"}, content="x" * 8193
        ).status_code
        == 413
    )


def test_plugin_permission_failure_precedes_service_io(tmp_path: Path) -> None:
    client, service = _client(tmp_path, scopes=["agent.run"])
    assert client.get(PREFIX, headers=AUTH).status_code == 403
    assert client.post(PREFIX, headers=AUTH, json={}).status_code == 403
    assert not service.mock_calls
