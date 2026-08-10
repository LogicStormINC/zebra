from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
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
from zebra_agent_worker.loop import build_worker_loop_service


class _ObjectReader:
    def verify(self, expectation: ArtifactObjectExpectation) -> ArtifactObjectVerification:
        raise AssertionError(expectation)

    def read_version_verified(
        self,
        expectation: ArtifactObjectExpectation,
        object_version: str,
    ) -> bytes:
        raise AssertionError((expectation, object_version))


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


class _CloudLikeStores:
    def __init__(self, delegate: ControlPlaneStores) -> None:
        self._delegate = delegate
        self.deployment_namespace = "deployment"

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


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
    local = compose_control_plane_stores(profile="local", database_path=tmp_path / "local.sqlite")
    assert isinstance(local, ControlPlaneStores)

    calls: list[dict[str, object]] = []

    def fake_postgres(dsn: str, **kwargs: object) -> object:
        calls.append({"dsn": dsn, **kwargs})
        return object()

    monkeypatch.setattr(
        "agent_storage.runtime_composition.postgres_control_plane_stores", fake_postgres
    )
    cloud = compose_control_plane_stores(
        profile="cloud",
        database_path=tmp_path / "ignored.sqlite",
        cloud=_cloud_settings(),
    )
    assert len(calls) == 1
    assert calls[0]["dsn"] == "postgresql://zebra:test@localhost/zebra"
    assert calls[0]["deployment_namespace"] == "deployment"
    assert calls[0]["memory_cursor_signing_key"] == b"k" * 32
    assert calls[0]["history_scope"] == _cloud_settings().history_scope
    assert calls[0]["continuation_scope"] == _cloud_settings().continuation_scope
    assert cloud is not local


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


def test_api_cloud_profile_uses_shared_composition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": "cloud",
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
    api = create_app(settings=settings, cloud_composition=_cloud_settings())
    assert captured["profile"] == "cloud"
    assert api.stores is local


def test_worker_cloud_profile_uses_shared_composition_without_sqlite_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": "cloud",
            "ZEBRA_DATABASE_URL": "postgresql://zebra:test@localhost/zebra",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )
    local = sqlite_control_plane_stores(tmp_path / "worker.sqlite")
    cloud_like = _CloudLikeStores(local)
    captured: dict[str, object] = {}

    def fake_compose(**kwargs: object) -> Any:
        captured.update(kwargs)
        return cloud_like

    monkeypatch.setattr("zebra_agent_worker.loop.compose_control_plane_stores", fake_compose)
    build_worker_loop_service(
        database_path=tmp_path / "ignored.sqlite",
        settings=settings,
        cloud_composition=_cloud_settings(),
        sleep=lambda _: None,
    )
    assert captured["profile"] == "cloud"
