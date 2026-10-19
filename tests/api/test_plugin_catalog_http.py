"""Approved marketplace descriptors reuse fresh extension authority and hide package bytes."""

from pathlib import Path

import pytest
from agent_core.ports.plugin_installations import (
    PluginPackageCatalogEntry,
    PluginPackageCatalogPage,
)

from tests.api.test_plugin_installations_http import AUTH, _client


def test_catalog_is_read_only_bounded_and_redacts_paths(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    package = service.store.get.return_value.package
    service.publisher.list_packages.return_value = PluginPackageCatalogPage(
        items=(
            PluginPackageCatalogEntry(
                package_digest=package.package_digest, manifest=package.manifest
            ),
        )
    )
    result = client.get("/v1/extensions/plugin-packages?limit=1", headers=AUTH)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    item = result.json()["items"][0]
    assert set(item) == {"package_digest", "plugin_id", "version", "publisher", "components"}
    assert set(item["components"][0]) == {"component_id", "kind"}
    assert service.publisher.list_packages.call_args.kwargs["page"].limit == 1
    service.publisher.publish.assert_not_called()
    service.install.assert_not_called()
    assert client.post("/v1/extensions/plugin-packages", headers=AUTH, json={}).status_code == 405
    assert client.get("/v1/extensions/plugin-packages?limit=101", headers=AUTH).status_code == 422
    assert (
        client.get("/v1/extensions/plugin-packages?principal_id=other", headers=AUTH).status_code
        == 422
    )


@pytest.mark.parametrize(
    "local,enabled,scopes,status",
    [
        (True, True, ["extensions.read"], 404),
        (False, False, ["extensions.read"], 404),
        (False, True, ["agent.run"], 403),
    ],
)
def test_catalog_gate_precedes_package_io(tmp_path, local, enabled, scopes, status):
    client, service = _client(tmp_path, local=local, enabled=enabled, scopes=scopes)
    assert client.get("/v1/extensions/plugin-packages", headers=AUTH).status_code == status
    assert not service.mock_calls


def test_unavailable_catalog_is_not_an_empty_market(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    service.publisher.list_packages.side_effect = RuntimeError("private diagnostic")
    result = client.get("/v1/extensions/plugin-packages", headers=AUTH)
    assert result.status_code == 503 and "private diagnostic" not in result.text
