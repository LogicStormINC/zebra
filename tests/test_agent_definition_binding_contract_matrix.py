"""AGENT-DEF-BIND-01 contract matrix: Task-level Definition binding."""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.agent_definition_binding import (
    DefinitionBindingError,
    DefinitionBindingService,
    EvalBindingDeniedError,
    NoPublishedReleaseError,
)
from agent_core.application.agent_definitions import (
    PublisherGrantCeiling,
    StaticPublisherGrantResolver,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_definition_snapshots import (
    AgentDefinitionSnapshot,
    BindingPurpose,
    canonical_agent_definition_snapshot_digest,
)
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionScope,
    AgentDefinitionVersion,
    AgentRelease,
    AgentReleaseStatus,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
    AgentReleaseId,
    new_session_id,
)
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_storage import sqlite_control_plane_stores

DIGEST = sha256(b"skill-snapshot").hexdigest()
CREATED = datetime(2026, 8, 16, 11, 0, tzinfo=UTC)
ISSUER = "https://issuer.example"

GRANTED_REFS = frozenset(
    {
        "policies/models/deepseek@v4",
        "policies/tools/general@v2",
        "policies/memory/workspace@v1",
        "policies/security/strict@v3",
        "policies/evals/release@v5",
        "policies/runtime/gvisor@v1",
    }
)


class _MemoryRegistry:
    """In-memory registry with a configurable digest-mismatch switch."""

    def __init__(self) -> None:
        self.definitions: dict[tuple, AgentDefinition] = {}
        self.versions: dict[tuple, AgentDefinitionVersion] = {}
        self.releases: list[AgentRelease] = []
        self.corrupt_version_digest = False

    def _scope_key(self, scope: AgentDefinitionScope) -> tuple:
        return scope.scope_key

    def get_definition(self, scope: AgentDefinitionScope) -> AgentDefinition | None:
        return self.definitions.get(self._scope_key(scope))

    def save_definition(
        self,
        definition: AgentDefinition,
        *,
        expected_revision: int | None = None,
    ) -> AgentDefinition:
        self.definitions[self._scope_key(definition.scope)] = definition
        return definition

    def save_version(self, version: AgentDefinitionVersion) -> AgentDefinitionVersion:
        stored = version
        if self.corrupt_version_digest and version.version_id is not None:
            stored = version.model_copy(
                update={"definition_digest": sha256(b"corrupt").hexdigest()}
            )
        self.versions[(self._scope_key(version.scope), version.version_id)] = stored
        return stored

    def get_version(
        self,
        scope: AgentDefinitionScope,
        version_id: AgentDefinitionVersionId,
    ) -> AgentDefinitionVersion | None:
        return self.versions.get((self._scope_key(scope), version_id))

    def resolve_published(
        self,
        scope: AgentDefinitionScope,
        *,
        environment: str,
    ) -> AgentRelease | None:
        matches = [
            release
            for release in self.releases
            if release.authority_issuer == scope.authority_issuer
            and release.namespace_id == scope.namespace_id
            and release.definition_id == scope.definition_id
            and release.environment == environment
            and release.status is AgentReleaseStatus.PUBLISHED
        ]
        if not matches:
            return None
        return max(matches, key=lambda release: release.revision)

    def append_release(
        self,
        release: AgentRelease,
        *,
        expected_revision: int | None = None,
    ) -> AgentRelease:
        self.releases.append(release)
        return release

    def get_draft(self, scope: AgentDefinitionScope) -> None:
        return None

    def save_draft(self, draft: Any, *, expected_revision: int | None = None) -> Any:
        return draft

    def append_draft_validation(self, validation: Any) -> None:
        del validation

    def latest_draft_validation(self, scope: AgentDefinitionScope) -> None:
        return None

    def record_eval_evidence(self, evidence: Any) -> None:
        del evidence

    def latest_eval_evidence(self, scope: AgentDefinitionScope, version_id: Any) -> None:
        return None


def _definition(definition_id: AgentDefinitionId | None = None) -> AgentDefinition:
    return AgentDefinition(
        definition_id=definition_id or AgentDefinitionId(uuid4()),
        authority_issuer=ISSUER,
        namespace_id="tenant-a",
        name="code-agent",
        description="Primary coding agent",
        revision=0,
        created_at=CREATED,
    )


def _version(
    definition: AgentDefinition,
    *,
    version_number: int = 1,
) -> AgentDefinitionVersion:
    return AgentDefinitionVersion.from_definition(
        definition,
        version_id=AgentDefinitionVersionId(uuid4()),
        version=version_number,
        created_at=CREATED,
        model_policy_ref="policies/models/deepseek@v4",
        tool_profile_ref="policies/tools/general@v2",
        skill_snapshot_digest=DIGEST,
        memory_policy_ref="policies/memory/workspace@v1",
        security_policy_ref="policies/security/strict@v3",
        evaluation_profile_ref="policies/evals/release@v5",
        runtime_profile_ref="policies/runtime/gvisor@v1",
    )


def _release(version: AgentDefinitionVersion) -> AgentRelease:
    return AgentRelease.from_version(
        version,
        release_id=AgentReleaseId(uuid4()),
        environment="production",
        actor_ref="release-bot",
        effective_at=CREATED,
    )


def _grants() -> StaticPublisherGrantResolver:
    return StaticPublisherGrantResolver(
        {
            "publisher-b@tenant-a": PublisherGrantCeiling(
                authority_issuer=ISSUER,
                namespace_id="tenant-a",
                allowed_references=GRANTED_REFS,
            )
        }
    )


def _binding_service(
    registry: _MemoryRegistry,
) -> DefinitionBindingService:
    return DefinitionBindingService(registry, _grants())


def test_production_binding_resolves_published_release() -> None:
    registry = _MemoryRegistry()
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    release = registry.append_release(_release(version))
    snapshot = _binding_service(registry).resolve_production_snapshot(
        definition.scope,
        environment="production",
        resolved_at=CREATED,
    )
    assert snapshot.binding_purpose is BindingPurpose.PRODUCTION
    assert snapshot.release_id == release.release_id
    assert snapshot.release_revision == release.revision
    assert snapshot.release_status is release.status
    assert snapshot.definition_digest == version.definition_digest
    assert snapshot.version_id == version.version_id
    assert (
        canonical_agent_definition_snapshot_digest(snapshot) == snapshot.snapshot_digest
    )


def test_production_binding_without_release_fails_closed() -> None:
    registry = _MemoryRegistry()
    definition = registry.save_definition(_definition())
    registry.save_version(_version(definition))
    with pytest.raises(NoPublishedReleaseError):
        _binding_service(registry).resolve_production_snapshot(
            definition.scope,
            environment="production",
            resolved_at=CREATED,
        )


def test_production_binding_digest_mismatch_fails_closed() -> None:
    registry = _MemoryRegistry()
    registry.corrupt_version_digest = True
    definition = registry.save_definition(_definition())
    original = _version(definition)
    registry.save_version(original)
    registry.append_release(_release(original))
    with pytest.raises(DefinitionBindingError, match="digest"):
        _binding_service(registry).resolve_production_snapshot(
            definition.scope,
            environment="production",
            resolved_at=CREATED,
        )


def test_eval_binding_pins_version_without_release() -> None:
    registry = _MemoryRegistry()
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    snapshot = _binding_service(registry).resolve_eval_snapshot(
        definition.scope,
        environment="staging",
        version_id=version.version_id,
        actor_ref="publisher-b",
        resolved_at=CREATED,
    )
    assert snapshot.binding_purpose is BindingPurpose.EVAL
    assert snapshot.release_id is None
    assert snapshot.release_revision is None
    assert snapshot.release_status is None
    assert snapshot.version_id == version.version_id


def test_eval_binding_denied_in_production_and_without_grant() -> None:
    registry = _MemoryRegistry()
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    service = _binding_service(registry)
    with pytest.raises(EvalBindingDeniedError, match="production"):
        service.resolve_eval_snapshot(
            definition.scope,
            environment="production",
            version_id=version.version_id,
            actor_ref="publisher-b",
            resolved_at=CREATED,
        )
    with pytest.raises(EvalBindingDeniedError, match="authority"):
        service.resolve_eval_snapshot(
            definition.scope,
            environment="staging",
            version_id=version.version_id,
            actor_ref="unknown-actor",
            resolved_at=CREATED,
        )
    with pytest.raises(DefinitionBindingError, match="does not exist"):
        service.resolve_eval_snapshot(
            definition.scope,
            environment="staging",
            version_id=AgentDefinitionVersionId(uuid4()),
            actor_ref="publisher-b",
            resolved_at=CREATED,
        )


def test_task_prepared_carries_optional_snapshot_and_legacy_stays_unchanged() -> None:
    registry = _MemoryRegistry()
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    registry.append_release(_release(version))
    snapshot = _binding_service(registry).resolve_production_snapshot(
        definition.scope,
        environment="production",
        resolved_at=CREATED,
    )
    bound = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="t",
            user_input="run",
            workspace_root=Path("/tmp/w"),
            definition_snapshot=snapshot,
        )
    )
    prepared = next(
        event for event in bound.events if event.event_type is EventType.TASK_PREPARED
    )
    carried = AgentDefinitionSnapshot.model_validate(
        prepared.payload["definition_snapshot"]
    )
    assert carried == snapshot
    legacy = SessionBootstrapService().build(
        SessionBootstrapCommand(title="t", user_input="run", workspace_root=Path("/tmp/w"))
    )
    legacy_prepared = next(
        event
        for event in legacy.events
        if event.event_type is EventType.TASK_PREPARED
    )
    assert "definition_snapshot" not in legacy_prepared.payload


def test_workspace_projection_mirrors_snapshot_and_rejects_tampering(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    registry.append_release(_release(version))
    snapshot = _binding_service(registry).resolve_production_snapshot(
        definition.scope,
        environment="production",
        resolved_at=CREATED,
    )
    session = Session.create(title="t", created_at=CREATED)
    events = (
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor="user",
            payload={"title": "t"},
            created_at=CREATED,
        ),
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor="user",
            payload={"content": "run"},
            created_at=CREATED,
        ),
        SessionEvent.create(
            session_id=session.session_id,
            sequence=2,
            event_type=EventType.TASK_PREPARED,
            actor="harness",
            payload={
                "title": "t",
                "user_input": "run",
                "workspace_root": str(tmp_path),
                "definition_snapshot": snapshot.model_dump(
                    mode="json", exclude_none=True
                ),
            },
            created_at=CREATED,
        ),
    )
    projection = rebuild_workspace(list(events))
    assert projection.definition_snapshot == snapshot
    tampered = snapshot.model_dump(mode="json", exclude_none=True)
    tampered["model_policy_ref"] = "policies/models/deepseek@v9"
    with pytest.raises(ValueError):
        AgentDefinitionSnapshot.model_validate(tampered)


def test_worker_recovery_validates_snapshot_digest() -> None:
    from zebra_agent_worker.task_recovery import _definition_snapshot

    registry = _MemoryRegistry()
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    registry.append_release(_release(version))
    snapshot = _binding_service(registry).resolve_production_snapshot(
        definition.scope,
        environment="production",
        resolved_at=CREATED,
    )
    recovered = _definition_snapshot(snapshot.model_dump(mode="json", exclude_none=True))
    assert recovered == snapshot
    tampered = snapshot.model_dump(mode="json", exclude_none=True)
    tampered["snapshot_digest"] = sha256(b"tampered").hexdigest()
    with pytest.raises(ValueError, match="invalid"):
        _definition_snapshot(tampered)


def test_sqlite_workspace_store_roundtrips_snapshot(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    registry.append_release(_release(version))
    snapshot = _binding_service(registry).resolve_production_snapshot(
        definition.scope,
        environment="production",
        resolved_at=CREATED,
    )
    stores = sqlite_control_plane_stores(tmp_path / "control.sqlite")
    workspace = WorkspaceProjection(
        session_id=new_session_id(),
        workspace_root=str(tmp_path),
        prepared_at=CREATED,
        updated_at=CREATED,
        current_sequence=0,
        status="prepared",
        definition_snapshot=snapshot,
    )
    stores.workspaces.save_workspace(workspace)
    assert stores.workspaces.get_workspace(workspace.session_id) == workspace


def test_postgres_registry_and_workspace_snapshot_roundtrip(
    postgres_dsn: str,
    workspace_namespace: str,
) -> None:
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.sessions import Session
    from agent_storage import (
        PostgresAgentRegistry,
        PostgresEventStore,
        PostgresWorkspaceProjectionStore,
        apply_postgres_migrations,
    )

    apply_postgres_migrations(postgres_dsn)
    registry = PostgresAgentRegistry(
        postgres_dsn,
        deployment_namespace=workspace_namespace,
    )
    definition = registry.save_definition(_definition())
    version = registry.save_version(_version(definition))
    release = registry.append_release(_release(version))
    snapshot = DefinitionBindingService(registry, _grants()).resolve_production_snapshot(
        definition.scope,
        environment="production",
        resolved_at=CREATED,
    )
    assert snapshot.release_id == release.release_id
    session = Session.create(title="t", created_at=CREATED)
    PostgresEventStore(
        postgres_dsn,
        deployment_namespace=workspace_namespace,
    ).append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "t"},
            created_at=CREATED,
        )
    )
    store = PostgresWorkspaceProjectionStore(
        postgres_dsn,
        deployment_namespace=workspace_namespace,
    )
    workspace = WorkspaceProjection(
        session_id=session.session_id,
        workspace_root="/workspaces/proj",
        prepared_at=CREATED,
        updated_at=CREATED,
        current_sequence=0,
        status="prepared",
        definition_snapshot=snapshot,
    )
    store.save_workspace(workspace)
    stored = store.get_workspace(workspace.session_id)
    assert stored == workspace
    assert stored is not None and stored.definition_snapshot == snapshot


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    from agent_storage import apply_postgres_migrations

    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def workspace_namespace(postgres_dsn: str) -> Generator[str, None, None]:
    from agent_storage import bootstrap_control_plane_epoch

    namespace = f"binding-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def _delete_namespace(postgres_dsn: str, namespace: str) -> None:
    import psycopg

    with psycopg.connect(postgres_dsn) as connection:
        for table in (
            "workspace_projections",
            "session_events",
            "session_projections",
            "session_streams",
            "control_plane_epochs",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )
