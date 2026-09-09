"""Opt-in production composition, mounted key admission and real database readback."""

import asyncio
import base64
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from zebra_agent_api import extension_composition, http
from zebra_agent_api.mcp_credential_composition import compose_mcp_credentials
from zebra_agent_config import load_settings
from zebra_agent_config.mcp_credentials import McpCredentialSettings

from tests.agent_storage import test_mcp_credential_management as fixtures
from tests.api import test_skill_publication_composition as startup_fixtures
from tests.api.test_extension_composition import DSN, _cloud_composition
from tests.api.test_extension_credentials import AUTH, HEADERS, TOKEN
from tests.api.test_extension_reads import Authorizer
from tests.api.test_host_auth_http import _cloud_settings

dsn = fixtures.dsn
cloud_startup = startup_fixtures.cloud_startup
postgres_dsn = fixtures.postgres_dsn
protector = fixtures.protector


@pytest.fixture
def mounted(tmp_path):
    path = tmp_path / "master.json"
    path.write_text(json.dumps({"version": "v1", "value": base64.b64encode(b"k" * 32).decode()}))
    path.chmod(0o600)
    return replace(
        _cloud_settings(DSN),
        cloud_extensions_read_enabled=True,
        cloud_extensions_manage_enabled=True,
        mcp_credentials=McpCredentialSettings(True, str(tmp_path), "master", "v1"),
    )


def test_settings_default_and_references(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert not load_settings(env={}).mcp_credentials.enabled
    config = load_settings(
        env={
            "ZEBRA_CLOUD_MCP_CREDENTIALS_ENABLED": "true",
            "ZEBRA_MCP_SECRET_ROOT": "/run/secrets",
            "ZEBRA_MCP_KEY_HANDLE": "master",
            "ZEBRA_MCP_KEY_VERSION": "v2",
        }
    ).mcp_credentials
    assert config == McpCredentialSettings(True, "/run/secrets", "master", "v2")


@pytest.mark.parametrize("explicit", [False, True])
def test_shared_startup_authority(cloud_startup, mounted, explicit):
    resolver, schema = cloud_startup
    app = http.create_http_app(
        settings=mounted,
        host_grant_authorizer=Authorizer(),
        cloud_composition=resolver.return_value if explicit else None,
    )
    assert app is not None
    assert resolver.call_count == (0 if explicit else 1)
    assert all(call.args == (resolver.return_value.dsn,) for call in schema.call_args_list)


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": "local"},
        {"cloud_extensions_read_enabled": False},
        {"cloud_extensions_manage_enabled": False},
    ],
)
def test_invalid_composition_rejected_before_app(monkeypatch, mounted, changes):
    create = Mock(side_effect=AssertionError("must reject before storage construction"))
    monkeypatch.setattr(http, "create_app", create)
    with pytest.raises(ValueError, match="requires cloud PostgreSQL"):
        http.create_http_app(settings=replace(mounted, **changes))
    create.assert_not_called()


@pytest.mark.parametrize("argument", ["stores", "extension_store"])
def test_no_mixed_injected_stores(mounted, argument):
    with pytest.raises(ValueError, match="composed control plane"):
        http.create_http_app(settings=mounted, **{argument: Mock()})


@pytest.mark.parametrize(
    "change", ["missing", "version", "traversal", "relative", "permissions", "invalid", "short"]
)
def test_bad_key_fails_closed(mounted, tmp_path, change):
    config = mounted.mcp_credentials
    path = tmp_path / "master.json"
    if change == "missing":
        path.unlink()
    elif change == "version":
        config = replace(config, key_version="v2")
    elif change == "traversal":
        config = replace(config, key_handle="../master")
    elif change == "relative":
        config = replace(config, secret_root="relative")
    elif change == "permissions":
        path.chmod(0o644)
    else:
        path.write_text(
            json.dumps({"version": "v1", "value": TOKEN if change == "invalid" else "YWJj"})
        )
    with pytest.raises(ValueError, match="unavailable or insecure") as caught:
        compose_mcp_credentials(replace(mounted, mcp_credentials=config), _cloud_composition())
    assert TOKEN not in str(caught.value) and caught.value.__suppress_context__


def test_disabled_does_not_read_key(cloud_startup, monkeypatch, mounted):
    compose = Mock(side_effect=AssertionError("disabled feature must not read key"))
    monkeypatch.setattr(extension_composition, "compose_mcp_credentials", compose)
    http.create_http_app(
        settings=replace(mounted, mcp_credentials=McpCredentialSettings()),
        cloud_composition=_cloud_composition(),
        host_grant_authorizer=Authorizer(),
    )
    compose.assert_not_called()


def test_mounted_key_changes_are_not_cached(mounted, tmp_path):
    service = compose_mcp_credentials(mounted, _cloud_composition())
    (tmp_path / "master.json").unlink()
    with pytest.raises(ValueError, match="key unavailable"):
        service.protector.validate_active_key()


def test_real_startup_http_and_restart(dsn, protector, mounted):
    _, store, verified, scope = fixtures.management(dsn, protector)
    cloud = replace(_cloud_composition(), dsn=dsn, deployment_namespace="dev")
    path = "/v1/extensions/mcp-connections/mcp/credentials"

    def application(other=False):
        grant = fixtures._verified(sub="other") if other else verified
        return TestClient(
            http.create_http_app(
                settings=mounted, cloud_composition=cloud, host_grant_authorizer=Authorizer(grant)
            )
        )

    with application() as api:
        response = api.post(path, headers=HEADERS, json={"token": TOKEN})
        assert response.status_code == 200, response.text
        assert response.headers["etag"] == '"2"'
    with application(True) as api:
        assert api.delete(path, headers=AUTH | {"If-Match": '"2"'}).status_code == 404
    current = asyncio.run(store.get_connection(scope=scope, connection_id="mcp"))
    encrypted = asyncio.run(
        store.get(scope=scope, connection_id="mcp", credential_ref=current.credential_ref)
    )
    restarted = compose_mcp_credentials(mounted, cloud)
    assert restarted.protector.unseal(encrypted.binding, encrypted.envelope).value == TOKEN
    with application() as api:
        response = api.delete(path, headers=AUTH | {"If-Match": '"2"'})
        assert response.status_code == 200 and response.json()["auth_state"] == "revoked"
    assert asyncio.run(store.get_connection(scope=scope, connection_id="mcp")).revision == 3
