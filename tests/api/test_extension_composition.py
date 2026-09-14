"""Cloud extension opt-in admission without PostgreSQL I/O."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.ports.extensions import ExtensionStore
from agent_storage import CloudCompositionSettings, postgres_control_plane_stores
from agent_storage.postgres.migration_types import PostgresMigrationError
from zebra_agent_api import extension_composition, http
from zebra_agent_config import load_settings

from tests.api.test_extension_reads import AUTH, PREFIX, Authorizer, _client
from tests.api.test_host_auth_http import _cloud_settings, _local_settings

DSN = "postgresql://unused/zebra"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("malformed", False),
        ("", False),
    ],
)
def test_settings_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str | None,
    expected: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    env = {} if value is None else {"ZEBRA_CLOUD_EXTENSIONS_READ_ENABLED": value}
    assert load_settings(env=env).cloud_extensions_read_enabled is expected
    assert _cloud_settings(DSN).cloud_extensions_read_enabled is False


def test_turn_admission_flag_defaults_off_and_parses_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_settings(env={}).cloud_extension_turn_admission_enabled is False
    assert (
        load_settings(
            env={"ZEBRA_CLOUD_EXTENSION_TURN_ADMISSION_ENABLED": "true"}
        ).cloud_extension_turn_admission_enabled
        is True
    )


@pytest.fixture
def admission(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    schema = Mock()
    factory = Mock(return_value=AsyncMock(spec=ExtensionStore))
    monkeypatch.setattr(extension_composition, "require_current_schema", schema)
    monkeypatch.setattr(extension_composition, "PostgresExtensionStore", factory)
    monkeypatch.setattr("psycopg.connect", Mock(side_effect=AssertionError("unexpected DB I/O")))
    return schema, factory


def _cloud_composition() -> CloudCompositionSettings:
    scope = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="namespace")
    return CloudCompositionSettings(
        dsn="postgresql://override/zebra",
        deployment_namespace="active-stores-namespace",
        memory_cursor_signing_key=b"x" * 32,
        artifact_objects=Mock(),
        history_scope=scope,
        continuation_scope=scope,
    )


@pytest.mark.parametrize("override", [False, True])
def test_cloud_composes_after_schema_with_store_namespace(
    admission: tuple[Mock, Mock],
    override: bool,
) -> None:
    schema, factory = admission
    cloud = _cloud_composition()
    stores = postgres_control_plane_stores(
        DSN,
        deployment_namespace="active-stores-namespace",
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    calls = Mock()
    calls.attach_mock(schema, "schema")
    calls.attach_mock(factory, "factory")
    result = extension_composition.compose_extension_store(
        replace(_cloud_settings(DSN), cloud_extensions_read_enabled=True),
        stores,
        cloud_composition=cloud if override else None,
    )
    dsn = cloud.dsn if override else DSN
    schema.assert_called_once_with(dsn)
    factory.assert_called_once_with(dsn, deployment_namespace="active-stores-namespace")
    assert result is factory.return_value
    assert [call[0] for call in calls.mock_calls] == ["schema", "factory"]


@pytest.mark.parametrize(
    ("local", "enabled", "injected"),
    [
        (False, False, False),
        (False, False, True),
        (False, True, True),
        (True, False, False),
        (True, False, True),
        (True, True, False),
        (True, True, True),
    ],
)
def test_disabled_local_and_injected_skip_admission(
    admission: tuple[Mock, Mock],
    local: bool,
    enabled: bool,
    injected: bool,
) -> None:
    settings = _local_settings() if local else _cloud_settings(DSN)
    store = AsyncMock() if injected else None
    if store is not None:
        store.__bool__.return_value = False
    result = extension_composition.compose_extension_store(
        replace(settings, cloud_extensions_read_enabled=enabled),
        Mock(),
        extension_store=store,
    )
    assert result is (None if local else store)
    for operation in admission:
        operation.assert_not_called()


def test_cloud_rejects_non_postgres_stores(admission: tuple[Mock, Mock]) -> None:
    with pytest.raises(
        ValueError,
        match="^cloud extension reads require PostgreSQL control plane stores$",
    ):
        extension_composition.compose_extension_store(
            replace(_cloud_settings(DSN), cloud_extensions_read_enabled=True),
            Mock(),
        )
    for operation in admission:
        operation.assert_not_called()


def test_schema_failure_prevents_store_creation(admission: tuple[Mock, Mock]) -> None:
    schema, factory = admission
    cloud = _cloud_composition()
    stores = postgres_control_plane_stores(
        DSN,
        deployment_namespace="active",
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    schema.side_effect = PostgresMigrationError("schema mismatch")
    with pytest.raises(PostgresMigrationError, match="schema mismatch"):
        extension_composition.compose_extension_store(
            replace(_cloud_settings(DSN), cloud_extensions_read_enabled=True),
            stores,
        )
    factory.assert_not_called()


def test_namespace_mismatch_rejected_before_schema(admission: tuple[Mock, Mock]) -> None:
    cloud = _cloud_composition()
    stores = postgres_control_plane_stores(
        DSN,
        deployment_namespace="different-namespace",
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    with pytest.raises(
        ValueError,
        match="deployment namespace does not match control plane stores",
    ):
        extension_composition.compose_extension_store(
            replace(_cloud_settings(DSN), cloud_extensions_read_enabled=True),
            stores,
            cloud_composition=cloud,
        )
    for operation in admission:
        operation.assert_not_called()


def test_turn_admission_requires_read_store_and_postgres() -> None:
    settings = replace(_cloud_settings(DSN), cloud_extension_turn_admission_enabled=True)
    with pytest.raises(ValueError, match="requires extension reads"):
        extension_composition.compose_extension_turn_admission(settings, Mock(), None)

    enabled = replace(settings, cloud_extensions_read_enabled=True)
    with pytest.raises(ValueError, match="requires PostgreSQL stores"):
        extension_composition.compose_extension_turn_admission(
            enabled, Mock(), AsyncMock(spec=ExtensionStore)
        )


@pytest.mark.parametrize("mcp_enabled", [False, True])
def test_turn_admission_composes_exact_namespace_snapshot_authority(
    monkeypatch: pytest.MonkeyPatch,
    mcp_enabled: bool,
) -> None:
    from zebra_agent_config.mcp_credentials import McpCredentialSettings
    cloud = _cloud_composition()
    stores = postgres_control_plane_stores(
        DSN,
        deployment_namespace=cloud.deployment_namespace,
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    snapshots = Mock()
    factory = Mock(return_value=snapshots)
    monkeypatch.setattr(extension_composition, "PostgresExtensionSnapshotStore", factory)
    extension_store = AsyncMock(spec=ExtensionStore)
    result = extension_composition.compose_extension_turn_admission(
        replace(
            _cloud_settings(DSN),
            cloud_extensions_read_enabled=True,
            cloud_extension_turn_admission_enabled=True,
            mcp_credentials=McpCredentialSettings(worker_enabled=mcp_enabled),
        ),
        stores,
        extension_store,
        cloud_composition=cloud,
    )
    factory.assert_called_once_with(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace
    )
    assert result is not None
    assert result._snapshots is snapshots
    assert result._task_authority is snapshots
    assert (result._mcp_catalogs is not None) is mcp_enabled


def test_http_factory_passes_composed_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composed = AsyncMock(spec=ExtensionStore)
    compose = Mock(return_value=composed)
    read = AsyncMock(return_value=http.JSONResponse({"composed": True}))
    monkeypatch.setattr(extension_composition, "compose_extension_store", compose)
    monkeypatch.setattr(http, "extension_read_response", read)
    client = _client(tmp_path, None)
    response = client.get(f"{PREFIX}/skill-installations", headers=AUTH)
    assert response.json() == {"composed": True}
    compose.assert_called_once()
    assert compose.call_args.kwargs == {"cloud_composition": None, "extension_store": None}
    assert compose.call_args.args[1] is None
    assert read.await_args.kwargs == {
        "store": composed,
        "deployment": "cloud",
        "manage_enabled": False,
        "publications": None,
    }


@pytest.mark.parametrize("enabled", [False, True])
def test_local_http_factory_keeps_sqlite_lazy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    enabled: bool,
) -> None:
    connect = Mock(side_effect=AssertionError("unexpected SQLite initialization"))
    monkeypatch.setattr("sqlite3.connect", connect)
    http.create_http_app(
        tmp_path / "lazy.sqlite",
        settings=replace(_local_settings(), cloud_extensions_read_enabled=enabled),
    )
    connect.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_injected_cloud_http_factory_does_not_resolve_stores(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    class LazyApi:
        @property
        def stores(self) -> None:
            raise AssertionError("unexpected control plane store access")

    monkeypatch.setattr(http, "create_app", Mock(return_value=LazyApi()))
    http.create_http_app(
        settings=replace(_cloud_settings(DSN), cloud_extensions_read_enabled=enabled),
        extension_store=AsyncMock(spec=ExtensionStore),
        host_grant_authorizer=Authorizer(),
    )
