from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectDeleteRequest,
    ArtifactObjectDeleteResult,
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
    ArtifactObjectVerification,
)
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    PostgresModelCallProjectionAdapter,
    PostgresToolRunProjectionAdapter,
    cloud_composition_from_environment,
    compose_control_plane_stores,
    sqlite_control_plane_stores,
)
from zebra_agent_api.app import create_app
from zebra_agent_config import load_settings
from zebra_agent_worker.cloud_composition import CloudWorkerComposition
from zebra_agent_worker.loop import build_worker_loop_service


class _ObjectReader:
    def put_if_absent(self, request: ArtifactObjectPutRequest) -> ArtifactObjectReceipt:
        raise AssertionError(request)

    def verify(self, expectation: ArtifactObjectExpectation) -> ArtifactObjectVerification:
        raise AssertionError(expectation)

    def read_verified(self, expectation: ArtifactObjectExpectation) -> bytes:
        raise AssertionError(expectation)

    def read_version_verified(
        self,
        expectation: ArtifactObjectExpectation,
        object_version: str,
    ) -> bytes:
        raise AssertionError((expectation, object_version))

    def delete_if_version(self, request: ArtifactObjectDeleteRequest) -> ArtifactObjectDeleteResult:
        raise AssertionError(request)


class _Projection:
    def __init__(self) -> None:
        self.session_id = SessionId(uuid4())
        self.model = ModelCallRecord(
            session_id=self.session_id,
            sequence=1,
            provider="test",
            model_name="model",
            assistant_message="answer",
            tool_call_count=0,
            created_at=datetime.now(UTC),
        )
        self.tool = ToolRunRecord(
            session_id=self.session_id,
            sequence=2,
            tool_name="tool",
            status="completed",
            output="ok",
            created_at=datetime.now(UTC),
        )

    def list_model_calls(self, session_id: SessionId) -> list[ModelCallRecord]:
        return [self.model] if session_id == self.session_id else []

    def list_tool_runs(self, session_id: SessionId) -> list[ToolRunRecord]:
        return [self.tool] if session_id == self.session_id else []

    def replay_session(self, session_id: SessionId) -> int:
        del session_id
        return 0

    def index_worker_event(
        self,
        event: SessionEvent,
        *,
        authority: WorkerMutationAuthority,
    ) -> ModelCallRecord:
        del event, authority
        return self.model


def _cloud_settings() -> CloudCompositionSettings:
    scope = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="scope")
    return CloudCompositionSettings(
        dsn="postgresql://zebra:test@localhost/zebra",
        deployment_namespace="deployment",
        memory_cursor_signing_key=b"k" * 32,
        artifact_objects=_ObjectReader(),
        history_scope=scope,
        continuation_scope=scope,
    )


def test_local_profile_keeps_sqlite_and_cloud_selection_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "agent_storage.runtime_composition.require_current_schema",
        lambda dsn: order.append(("schema", dsn)),
    )
    local = compose_control_plane_stores(
        profile="local",
        storage_authority="sqlite",
        database_path=tmp_path / "local.sqlite",
    )
    assert isinstance(local, ControlPlaneStores)
    assert order == []

    calls: list[dict[str, object]] = []

    def fake_postgres(dsn: str, **kwargs: object) -> object:
        order.append(("stores", dsn))
        calls.append({"dsn": dsn, **kwargs})
        return object()

    monkeypatch.setattr(
        "agent_storage.runtime_composition.postgres_control_plane_stores", fake_postgres
    )
    cloud = compose_control_plane_stores(
        profile="cloud",
        storage_authority="postgresql",
        database_path=tmp_path / "ignored.sqlite",
        cloud=_cloud_settings(),
    )
    assert order == [("schema", _cloud_settings().dsn), ("stores", _cloud_settings().dsn)]
    assert len(calls) == 1
    assert calls[0]["dsn"] == "postgresql://zebra:test@localhost/zebra"
    assert calls[0]["deployment_namespace"] == "deployment"
    assert calls[0]["memory_cursor_signing_key"] == b"k" * 32
    assert calls[0]["history_scope"] == _cloud_settings().history_scope
    assert calls[0]["continuation_scope"] == _cloud_settings().continuation_scope
    assert cloud is not local


def test_cloud_schema_failure_aborts_store_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_schema(dsn: str) -> None:
        assert dsn == _cloud_settings().dsn
        raise RuntimeError("schema is not current")

    monkeypatch.setattr("agent_storage.runtime_composition.require_current_schema", reject_schema)
    monkeypatch.setattr(
        "agent_storage.runtime_composition.postgres_control_plane_stores",
        lambda *_a, **_k: pytest.fail("store factory ran after schema failure"),
    )
    monkeypatch.setattr(
        "agent_storage.runtime_composition.sqlite_control_plane_stores",
        lambda *_a, **_k: pytest.fail("schema failure fell back to SQLite"),
    )
    with pytest.raises(RuntimeError, match="schema is not current"):
        compose_control_plane_stores(
            profile="cloud",
            storage_authority="postgresql",
            database_path=tmp_path / "ignored.sqlite",
            cloud=_cloud_settings(),
        )


def test_cloud_environment_missing_required_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="ZEBRA_MEMORY_CURSOR_SIGNING_KEY"):
        cloud_composition_from_environment(
            {
                "ZEBRA_DATABASE_URL": "postgresql://zebra:test@localhost/zebra",
                "ZEBRA_DEPLOYMENT_NAMESPACE": "deployment",
            }
        )


def test_projection_compatibility_facades_use_one_event_derived_source() -> None:
    projection = _Projection()
    model = PostgresModelCallProjectionAdapter(projection)
    tool = PostgresToolRunProjectionAdapter(projection)
    assert model.list_for_session(projection.session_id) == [projection.model]
    assert tool.list_for_session(projection.session_id) == [projection.tool]
    with pytest.raises(RuntimeError, match="Event-derived"):
        model.upsert(projection.model)
    with pytest.raises(RuntimeError, match="Event-derived"):
        tool.upsert(projection.tool)


@pytest.mark.parametrize("profile", ["cloud", "production"])
def test_cloud_and_production_api_profiles_use_shared_composition(
    profile: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": profile,
            "ZEBRA_DATABASE_URL": "postgresql://zebra:test@localhost/zebra",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )
    local = sqlite_control_plane_stores(tmp_path / "api.sqlite")
    captured: dict[str, object] = {}

    def fake_compose(**kwargs: object) -> ControlPlaneStores:
        captured.update(kwargs)
        return local

    monkeypatch.setattr("zebra_agent_api.factory.compose_control_plane_stores", fake_compose)
    # This test replaces cloud stores with SQLite only to inspect forwarding;
    # direct-control authority composition is covered by the real PG API test.
    monkeypatch.setattr("zebra_agent_api.factory.PostgresDirectControl", lambda *a, **kw: None)
    monkeypatch.setattr(
        "zebra_agent_api.factory.PostgresCommandOutcomeReader", lambda *a, **kw: None
    )
    api = create_app(settings=settings, cloud_composition=_cloud_settings())
    assert captured["profile"] == profile
    assert captured["storage_authority"] == "postgresql"
    assert api.stores is local
    assert api.effect_state is local.effects


@pytest.mark.parametrize("profile", ["cloud", "production"])
def test_cloud_and_production_worker_profiles_use_shared_composition_without_sqlite_fallback(
    profile: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": profile,
            "ZEBRA_DATABASE_URL": "postgresql://zebra:test@localhost/zebra",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )
    local = sqlite_control_plane_stores(tmp_path / "worker.sqlite")
    captured: dict[str, object] = {}

    def fake_compose(cloud: CloudCompositionSettings) -> CloudWorkerComposition:
        captured["cloud"] = cloud
        return CloudWorkerComposition(
            stores=local,  # type: ignore[arg-type]
            effect_dispatch=local.effects,  # type: ignore[arg-type]
            projection_transaction=local.workspaces,  # type: ignore[arg-type]
            deployment_namespace="deployment",
            artifact_factory=lambda _: None,  # type: ignore[arg-type,return-value]
            provider_continuation_factory=lambda _: None,  # type: ignore[arg-type,return-value]
            dsn=cloud.dsn,
        )

    monkeypatch.setattr("zebra_agent_worker.loop.compose_cloud_worker", fake_compose)
    monkeypatch.setattr(
        "zebra_agent_worker.command_process_state.command_cutover_state", lambda *a, **kw: False
    )
    def capture_service(**kwargs: object) -> object:
        captured["service"] = kwargs
        return object()

    monkeypatch.setattr("zebra_agent_worker.loop.SessionExecutionService", capture_service)
    build_worker_loop_service(
        database_path=tmp_path / "ignored.sqlite",
        settings=settings,
        cloud_composition=_cloud_settings(),
        sleep=lambda _: None,
    )
    assert captured["cloud"] is not None
    assert cast(CloudCompositionSettings, captured["cloud"]).dsn == _cloud_settings().dsn
    service = cast(dict[str, object], captured["service"])
    assert service["extension_snapshot_store"] is None
    assert service["extension_skills"] is None


def test_worker_cloud_profile_rejects_local_store_injection(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": "cloud",
            "ZEBRA_DATABASE_URL": "postgresql://zebra:test@localhost/zebra",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )
    with pytest.raises(ValueError, match="CloudWorkerComposition"):
        build_worker_loop_service(
            database_path=tmp_path / "ignored.sqlite",
            settings=settings,
            stores=sqlite_control_plane_stores(tmp_path / "local.sqlite"),
            cloud_composition=_cloud_settings(),
            sleep=lambda _: None,
        )


def test_cloud_skill_worker_passes_one_bundle_and_requires_snapshot_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    base = {
        "ZEBRA_PROFILE": "cloud",
        "ZEBRA_DATABASE_URL": "postgresql://zebra:test@localhost/zebra",
        "ZEBRA_RUNTIME_CLASS": "gvisor",
        "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
        "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        "ZEBRA_CLOUD_SKILL_WORKER_ENABLED": "true",
    }
    with pytest.raises(ValueError, match="snapshot recovery"):
        build_worker_loop_service(
            database_path=tmp_path / "ignored.sqlite",
            settings=load_settings(env=base),
            cloud_composition=_cloud_settings(),
            sleep=lambda _: None,
        )

    settings = load_settings(env={
        **base, "ZEBRA_CLOUD_EXTENSION_WORKER_ENABLED": "true",
    })
    local = sqlite_control_plane_stores(tmp_path / "worker.sqlite")
    extension_snapshots, extensions, objects = object(), object(), _ObjectReader()
    bundle = CloudWorkerComposition(
        stores=local,  # type: ignore[arg-type]
        effect_dispatch=local.effects,  # type: ignore[arg-type]
        projection_transaction=local.workspaces,  # type: ignore[arg-type]
        deployment_namespace="deployment",
        artifact_factory=lambda _: None,  # type: ignore[arg-type,return-value]
        provider_continuation_factory=lambda _: None,  # type: ignore[arg-type,return-value]
        dsn=_cloud_settings().dsn,
        extension_snapshots=extension_snapshots,  # type: ignore[arg-type]
        extensions=extensions,  # type: ignore[arg-type]
        skill_objects=objects,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "zebra_agent_worker.command_process_state.command_cutover_state", lambda *a, **kw: False
    )

    def capture_service(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("zebra_agent_worker.loop.SessionExecutionService", capture_service)
    build_worker_loop_service(
        database_path=tmp_path / "ignored.sqlite", settings=settings,
        cloud_worker_composition=bundle, sleep=lambda _: None,
    )
    assert captured["extension_snapshot_store"] is extension_snapshots
    source = captured["extension_skills"]
    assert source.store is extensions  # type: ignore[attr-defined]
    assert source.objects is objects  # type: ignore[attr-defined]
