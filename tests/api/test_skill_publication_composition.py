"""HTTP startup shares a single admitted cloud authority for skill publication."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, PropertyMock

import pytest
from agent_storage import runtime_composition, sqlite_control_plane_stores
from agent_storage.postgres.migration_types import PostgresMigrationError
from agent_tools.skill_publications import SkillPublicationService
from fastapi.testclient import TestClient
from zebra_agent_api import extension_composition, factory, http
from zebra_agent_config import ZebraAgentSettings, load_settings

from tests.agent_security.test_extension_authority import _verified
from tests.api.test_extension_composition import DSN, _cloud_composition
from tests.api.test_extension_reads import AUTH, PREFIX, Authorizer
from tests.api.test_host_auth_http import _cloud_settings, _local_settings


@pytest.mark.parametrize("value,expected", [(None, False), ("false", False), ("off", False),
                                           ("true", True), ("on", True), ("1", True)])
def test_publish_setting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                         value: str | None, expected: bool) -> None:
    monkeypatch.chdir(tmp_path)
    env = {} if value is None else {"ZEBRA_CLOUD_SKILLS_PUBLISH_ENABLED": value}
    assert load_settings(env=env).cloud_skills_publish_enabled is expected


@pytest.fixture
def cloud_startup(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    resolver = Mock(return_value=_cloud_composition())
    schema = Mock()
    monkeypatch.setattr(extension_composition, "cloud_composition_from_environment", resolver)
    monkeypatch.setattr(factory, "cloud_composition_from_environment", resolver)
    monkeypatch.setattr(runtime_composition, "require_current_schema", schema)
    monkeypatch.setattr(extension_composition, "require_current_schema", schema)
    monkeypatch.setattr("psycopg.connect", Mock(side_effect=AssertionError("unexpected DB I/O")))
    return resolver, schema


@pytest.mark.parametrize("explicit", [False, True])
def test_http_startup_reuses_resolved_bundle(cloud_startup: tuple[Mock, Mock],
                                           monkeypatch: pytest.MonkeyPatch,
                                           explicit: bool) -> None:
    resolver, schema = cloud_startup
    cloud = resolver.return_value
    compose = Mock(wraps=factory.compose_control_plane_stores)
    extension = Mock(wraps=extension_composition.PostgresExtensionStore)
    publication = AsyncMock(return_value=http.JSONResponse({"ok": True}))
    monkeypatch.setattr(factory, "compose_control_plane_stores", compose)
    monkeypatch.setattr(extension_composition, "PostgresExtensionStore", extension)
    monkeypatch.setattr(http, "skill_publication_response", publication)
    app = http.create_http_app(
        settings=replace(_cloud_settings(DSN), cloud_extensions_read_enabled=True,
                         cloud_skills_publish_enabled=True),
        cloud_composition=cloud if explicit else None, host_grant_authorizer=Authorizer(),
    )
    with TestClient(app) as client:
        assert client.post(f"{PREFIX}/skill-packages", headers=AUTH).json() == {"ok": True}
    assert resolver.call_count == (0 if explicit else 1)
    assert compose.call_args.kwargs["cloud"] is cloud
    extension.assert_called_once_with(cloud.dsn, deployment_namespace=cloud.deployment_namespace)
    service = publication.await_args.kwargs["service"]
    assert isinstance(service, SkillPublicationService)
    assert service.objects is cloud.artifact_objects
    assert service.store._dsn == cloud.dsn != DSN
    assert service.store.deployment_namespace == service.deployment_namespace == (
        cloud.deployment_namespace
    )
    assert schema.call_count == 2
    assert all(call.args == (cloud.dsn,) for call in schema.call_args_list)


@pytest.mark.parametrize("reason", ["reads", "storage", "stores", "extensions"])
def test_auto_publish_fails_before_app_creation(cloud_startup: tuple[Mock, Mock],
                                              monkeypatch: pytest.MonkeyPatch,
                                              reason: str) -> None:
    resolver, _ = cloud_startup
    create = Mock(side_effect=AssertionError("must reject before control plane creation"))
    monkeypatch.setattr(http, "create_app", create)
    settings = replace(_cloud_settings(DSN), cloud_extensions_read_enabled=reason != "reads",
                       cloud_skills_publish_enabled=True)
    if reason == "storage":
        monkeypatch.setattr(ZebraAgentSettings, "storage_authority",
                            PropertyMock(return_value="sqlite"))
    with pytest.raises(ValueError, match="cloud skill publication|automatic skill publication"):
        http.create_http_app(settings=settings,
                             stores=Mock() if reason == "stores" else None,
                             extension_store=AsyncMock() if reason == "extensions" else None)
    create.assert_not_called()
    resolver.assert_not_called()


def test_schema_failure_prevents_publication_composition(cloud_startup: tuple[Mock, Mock],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    _, schema = cloud_startup
    schema.side_effect = PostgresMigrationError("schema mismatch")
    service = Mock()
    monkeypatch.setattr(extension_composition, "SkillPublicationService", service)
    with pytest.raises(PostgresMigrationError, match="schema mismatch"):
        http.create_http_app(settings=replace(_cloud_settings(DSN),
                             cloud_extensions_read_enabled=True, cloud_skills_publish_enabled=True))
    service.assert_not_called()


@pytest.mark.parametrize("local,enabled", [(True, False), (True, True), (False, False)])
def test_disabled_and_local_skip_extra_resolution(cloud_startup: tuple[Mock, Mock],
                                                monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: Path, local: bool,
                                                enabled: bool) -> None:
    resolver, schema = cloud_startup
    stores = None if local else sqlite_control_plane_stores(tmp_path / "cloud.sqlite")
    monkeypatch.setattr("sqlite3.connect", Mock(side_effect=AssertionError("unexpected SQLite")))
    http.create_http_app(
        tmp_path / "lazy.sqlite",
        settings=replace(_local_settings() if local else _cloud_settings(DSN),
                         cloud_skills_publish_enabled=enabled),
        stores=stores,
        host_grant_authorizer=Authorizer(),
    )
    resolver.assert_not_called()
    schema.assert_not_called()


def test_default_off_cloud_resolves_only_existing_control_plane_bundle(
    cloud_startup: tuple[Mock, Mock], monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver, schema = cloud_startup
    service = Mock()
    monkeypatch.setattr(extension_composition, "SkillPublicationService", service)
    http.create_http_app(settings=_cloud_settings(DSN), host_grant_authorizer=Authorizer())
    resolver.assert_called_once_with()
    schema.assert_called_once_with(resolver.return_value.dsn)
    service.assert_not_called()


@pytest.mark.parametrize("manage,scopes,status", [
    (False, ["extensions.read", "extensions.manage"], 404),
    (True, ["extensions.read"], 403),
    (True, ["extensions.read", "extensions.manage"], 415),
])
def test_auto_service_keeps_post_guards(cloud_startup: tuple[Mock, Mock],
                                       manage: bool, scopes: list[str], status: int) -> None:
    app = http.create_http_app(
        settings=replace(_cloud_settings(DSN), cloud_extensions_read_enabled=True,
                         cloud_extensions_manage_enabled=manage, cloud_skills_publish_enabled=True),
        host_grant_authorizer=Authorizer(_verified(scopes=scopes)),
    )
    with TestClient(app) as client:
        assert client.post(f"{PREFIX}/skill-packages", headers=AUTH).status_code == status


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("read,manage,scopes,status", [
    (False, True, ["extensions.read", "extensions.manage"], 404),
    (True, False, ["extensions.read", "extensions.manage"], 404),
    (True, True, ["extensions.read"], 403),
    (True, True, ["extensions.read", "extensions.manage"], 415),
])
def test_explicit_service_http_guards_unchanged(cloud_startup: tuple[Mock, Mock], tmp_path: Path,
                                              enabled: bool, read: bool, manage: bool,
                                              scopes: list[str], status: int) -> None:
    resolver, schema = cloud_startup
    service = SkillPublicationService(AsyncMock(), Mock(), "explicit")
    app = http.create_http_app(
        settings=replace(_cloud_settings(DSN), cloud_extensions_read_enabled=read,
                         cloud_extensions_manage_enabled=manage,
                         cloud_skills_publish_enabled=enabled),
        stores=sqlite_control_plane_stores(tmp_path / "injected.sqlite"),
        extension_store=AsyncMock(), skill_publication_service=service,
        host_grant_authorizer=Authorizer(_verified(scopes=scopes)),
    )
    with TestClient(app) as client:
        response = client.post(f"{PREFIX}/skill-packages", headers=AUTH, content=b"unread")
    assert response.status_code == status
    service.store.reserve.assert_not_called()
    resolver.assert_not_called()
    schema.assert_not_called()
