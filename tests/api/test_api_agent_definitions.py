"""Route-level coverage for the bounded Agent Definition draft surface."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from agent_core.application.agent_definitions import (
    PublisherGrantCeiling,
    StaticPublisherGrantResolver,
)
from agent_core.domain.agent_definition_drafts import (
    AgentDefinitionDraft,
    AgentDefinitionDraftValidation,
)
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionScope,
    AgentRelease,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
)
from agent_storage import sqlite_control_plane_stores
from zebra_agent_api import create_app
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteAdapter, RouteRequest

DIGEST = sha256(b"skill-snapshot").hexdigest()
CREATED = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)

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


def _host_context(namespace_id: str = "tenant-a") -> HostContextEnvelope:
    from agent_core.domain.host_authority import HostResourceRef, HostTechnicalLimits

    return HostContextEnvelope(
        grant_id="grant-pub-1",
        host_app_id="publisher-b",
        namespace_id=namespace_id,
        workspace_ref="workspace://unit",
        resource_refs=(HostResourceRef(type="trench.event", id="evt-1"),),
        scopes=("agent-definition:publish",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=3600,
            max_model_tokens=100_000,
            max_artifact_bytes=1_000_000,
        ),
        origin="https://issuer.example",
        policy_version="policies/host/policy@v1",
    )


class _MemoryRegistry:
    """Minimal in-memory AgentRegistryPort for API route tests."""

    def __init__(self) -> None:
        self.definitions: dict[tuple, AgentDefinition] = {}
        self.drafts: dict[tuple, AgentDefinitionDraft] = {}
        self.validations: dict[tuple, list[AgentDefinitionDraftValidation]] = {}
        self.versions: dict[tuple, object] = {}
        self.releases: list[AgentRelease] = []

    def get_definition(self, scope: AgentDefinitionScope) -> AgentDefinition | None:
        return self.definitions.get(scope.scope_key)

    def save_definition(
        self,
        definition: AgentDefinition,
        *,
        expected_revision: int | None = None,
    ) -> AgentDefinition:
        existing = self.definitions.get(definition.scope.scope_key)
        if existing is not None and expected_revision != existing.revision:
            raise ValueError("Definition revision conflict")
        self.definitions[definition.scope.scope_key] = definition
        return definition

    def get_draft(self, scope: AgentDefinitionScope) -> AgentDefinitionDraft | None:
        return self.drafts.get(scope.scope_key)

    def save_draft(
        self,
        draft: AgentDefinitionDraft,
        *,
        expected_revision: int | None = None,
    ) -> AgentDefinitionDraft:
        existing = self.drafts.get(draft.scope.scope_key)
        if existing is None:
            if expected_revision is not None:
                raise ValueError("cannot create with expected revision")
            self.drafts[draft.scope.scope_key] = draft
            return draft
        if expected_revision is None or expected_revision != existing.revision:
            raise ValueError("Draft revision conflict")
        self.drafts[draft.scope.scope_key] = draft
        return draft

    def append_draft_validation(self, validation: AgentDefinitionDraftValidation) -> None:
        self.validations.setdefault(validation.scope.scope_key, []).append(validation)

    def latest_draft_validation(
        self, scope: AgentDefinitionScope
    ) -> AgentDefinitionDraftValidation | None:
        records = self.validations.get(scope.scope_key, [])
        return records[-1] if records else None

    def get_version(self, scope: AgentDefinitionScope, version_id: object) -> object:
        return self.versions.get((scope.scope_key, version_id))

    def save_version(self, version: object) -> object:
        scope = version.scope
        self.versions[(scope.scope_key, version.version_id)] = version
        return version

    def resolve_published(
        self, scope: AgentDefinitionScope, *, environment: str
    ) -> AgentRelease | None:
        from agent_core.domain.agent_definitions import AgentReleaseStatus

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
        self, release: AgentRelease, *, expected_revision: int | None = None
    ) -> AgentRelease:
        self.releases = [
            existing
            for existing in self.releases
            if existing.release_id != release.release_id
        ]
        self.releases.append(release)
        return release

    def record_eval_evidence(self, evidence: object) -> None:
        del evidence

    def latest_eval_evidence(self, scope: AgentDefinitionScope, version_id: object) -> None:
        return None


def _adapter(tmp_path: Path, registry: _MemoryRegistry) -> RouteAdapter:
    stores = sqlite_control_plane_stores(tmp_path / "control.sqlite")
    grants = StaticPublisherGrantResolver(
        {
            "publisher-b@tenant-a": PublisherGrantCeiling(
                authority_issuer="https://issuer.example",
                namespace_id="tenant-a",
                allowed_references=GRANTED_REFS,
            )
        }
    )
    app = create_app(
        str(tmp_path / "api.sqlite"),
        settings=_settings(),
        stores=stores,
        agent_registry=registry,
        publisher_grants=grants,
    )
    return RouteAdapter(app)


def _settings() -> object:
    from zebra_agent_config import load_settings

    return load_settings(env={"ZEBRA_PROFILE": "local"})


def _definition_payload() -> dict[str, object]:
    return {
        "name": "code-agent",
        "description": "Primary coding agent",
        "model_policy_ref": "policies/models/deepseek@v4",
        "tool_profile_ref": "policies/tools/general@v2",
        "skill_snapshot_digest": DIGEST,
        "memory_policy_ref": "policies/memory/workspace@v1",
        "security_policy_ref": "policies/security/strict@v3",
        "evaluation_profile_ref": "policies/evals/release@v5",
        "runtime_profile_ref": "policies/runtime/gvisor@v1",
    }


def _post(
    adapter: RouteAdapter,
    path: str,
    body: dict[str, object],
    *,
    host_context: HostContextEnvelope | None = None,
) -> ApiResponse:
    return adapter.handle(
        RouteRequest(
            method="POST",
            path=path,
            body=body,
            host_context=host_context,
        )
    )


def test_draft_create_validate_materialize_flow(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    created = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        _definition_payload(),
        host_context=_host_context(),
    )
    assert created.status_code == 200
    assert created.body["revision"] == 0
    validation = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft/validate",
        {},
        host_context=_host_context(),
    )
    assert validation.status_code == 200
    assert validation.body["status"] == "passed"
    version_id = str(AgentDefinitionVersionId(uuid4()))
    materialized = _post(
        adapter,
        f"/agent-definitions/{definition_id}/versions",
        {"version_id": version_id, "version": 1},
        host_context=_host_context(),
    )
    assert materialized.status_code == 201
    assert materialized.body["version"] == 1
    assert materialized.body["model_policy_ref"] == "policies/models/deepseek@v4"


def test_materialize_without_validation_fails_closed(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    created = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        _definition_payload(),
        host_context=_host_context(),
    )
    assert created.status_code == 200
    materialized = _post(
        adapter,
        f"/agent-definitions/{definition_id}/versions",
        {"version_id": str(AgentDefinitionVersionId(uuid4())), "version": 1},
        host_context=_host_context(),
    )
    assert materialized.status_code == 400


def test_unpinned_and_ungranted_references_fail_validation(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    unpinned = _definition_payload()
    unpinned["tool_profile_ref"] = "policies/tools/general@latest"
    rejected = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        unpinned,
        host_context=_host_context(),
    )
    assert rejected.status_code == 400
    ungranted = _definition_payload()
    ungranted["model_policy_ref"] = "policies/models/deepseek@v5"
    created = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        ungranted,
        host_context=_host_context(),
    )
    assert created.status_code == 200
    validation = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft/validate",
        {},
        host_context=_host_context(),
    )
    assert validation.status_code == 200
    assert validation.body["status"] == "failed"
    codes = {issue["code"] for issue in validation.body["issues"]}
    assert "reference-not-granted" in codes
    materialized = _post(
        adapter,
        f"/agent-definitions/{definition_id}/versions",
        {"version_id": str(AgentDefinitionVersionId(uuid4())), "version": 1},
        host_context=_host_context(),
    )
    assert materialized.status_code == 400


def test_update_uses_optimistic_revision_cas(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    created = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        _definition_payload(),
        host_context=_host_context(),
    )
    assert created.status_code == 200
    updated = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        {"description": "v2", "expected_revision": 0},
        host_context=_host_context(),
    )
    assert updated.status_code == 200
    assert updated.body["revision"] == 1
    stale = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        {"description": "v3", "expected_revision": 0},
        host_context=_host_context(),
    )
    assert stale.status_code == 409


def test_cross_namespace_and_missing_grant_fail_closed(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    response = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        _definition_payload(),
        host_context=_host_context(namespace_id="tenant-b"),
    )
    assert response.status_code == 403
    response = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        _definition_payload(),
        host_context=None,
    )
    assert response.status_code == 403


def test_no_registry_composed_fails_closed(tmp_path: Path) -> None:
    stores = sqlite_control_plane_stores(tmp_path / "control.sqlite")
    app = create_app(
        str(tmp_path / "api.sqlite"),
        settings=_settings(),
        stores=stores,
    )
    adapter = RouteAdapter(app)
    response = _post(
        adapter,
        f"/agent-definitions/{str(AgentDefinitionId(uuid4()))}/draft",
        _definition_payload(),
        host_context=_host_context(),
    )
    assert response.status_code == 503


def test_non_publication_routes_do_not_exist(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    response = _post(
        adapter,
        f"/agent-definitions/{definition_id}/marketplace",
        {"version_id": str(AgentDefinitionVersionId(uuid4()))},
        host_context=_host_context(),
    )
    assert response.status_code == 404


def test_unknown_draft_fields_rejected(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    payload = _definition_payload()
    payload["api_key"] = "hunter2"
    response = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        payload,
        host_context=_host_context(),
    )
    assert response.status_code == 400


def _publish_payload(
    registry: _MemoryRegistry,
    adapter: RouteAdapter,
    definition_id: str,
) -> dict[str, object]:
    """Create draft, validate, materialize; return a valid publish payload."""
    created = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft",
        _definition_payload(),
        host_context=_host_context(),
    )
    assert created.status_code == 200
    validation = _post(
        adapter,
        f"/agent-definitions/{definition_id}/draft/validate",
        {},
        host_context=_host_context(),
    )
    assert validation.status_code == 200
    version_id = str(AgentDefinitionVersionId(uuid4()))
    materialized = _post(
        adapter,
        f"/agent-definitions/{definition_id}/versions",
        {"version_id": version_id, "version": 1},
        host_context=_host_context(),
    )
    assert materialized.status_code == 201
    digest = materialized.body["definition_digest"]
    return {
        "version_id": version_id,
        "environment": "production",
        "gate": {
            "passed": True,
            "policy_version": "policies/evals/release@v5",
            "definition_digest": digest,
        },
    }


def test_publish_requires_passing_gate_and_supersedes_atomically(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    payload = _publish_payload(registry, adapter, definition_id)
    denied = _post(
        adapter,
        f"/agent-definitions/{definition_id}/release",
        {**payload, "gate": {**payload["gate"], "passed": False}},
        host_context=_host_context(),
    )
    assert denied.status_code == 409
    published = _post(
        adapter,
        f"/agent-definitions/{definition_id}/release",
        payload,
        host_context=_host_context(),
    )
    assert published.status_code == 201
    assert published.body["status"] == "published"
    scope = _scope_of(registry, definition_id)
    resolved = registry.resolve_published(scope, environment="production")
    assert resolved is not None
    assert str(resolved.version_id) == payload["version_id"]
    # republishing the same version is idempotent at the service level
    replayed = _post(
        adapter,
        f"/agent-definitions/{definition_id}/release",
        payload,
        host_context=_host_context(),
    )
    assert replayed.status_code == 201


def _scope_of(registry: _MemoryRegistry, definition_id: str) -> AgentDefinitionScope:
    return AgentDefinitionScope(
        authority_issuer="https://issuer.example",
        namespace_id="tenant-a",
        definition_id=AgentDefinitionId(definition_id),
    )


def test_deprecate_and_revoke_append_typed_evidence(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    adapter = _adapter(tmp_path, registry)
    definition_id = str(AgentDefinitionId(uuid4()))
    payload = _publish_payload(registry, adapter, definition_id)
    published = _post(
        adapter,
        f"/agent-definitions/{definition_id}/release",
        payload,
        host_context=_host_context(),
    )
    assert published.status_code == 201
    deprecated = _post(
        adapter,
        f"/agent-definitions/{definition_id}/release/deprecate",
        {
            "environment": "production",
            "reason_class": "rollback",
            "enforcement_mode": "safe-boundary",
        },
        host_context=_host_context(),
    )
    assert deprecated.status_code == 200
    assert deprecated.body["status"] == "deprecated"
    assert deprecated.body["reason_class"] == "rollback"
    assert deprecated.body["enforcement_mode"] == "safe-boundary"
    scope = _scope_of(registry, definition_id)
    assert registry.resolve_published(scope, environment="production") is None
    revoked = _post(
        adapter,
        f"/agent-definitions/{definition_id}/release/revoke",
        {
            "environment": "production",
            "reason_class": "security",
            "enforcement_mode": "immediate",
        },
        host_context=_host_context(),
    )
    assert revoked.status_code == 403


def test_immediate_revoke_requires_security_authority(tmp_path: Path) -> None:
    registry = _MemoryRegistry()
    stores = sqlite_control_plane_stores(tmp_path / "control.sqlite")
    grants = StaticPublisherGrantResolver(
        {
            "publisher-b@tenant-a": PublisherGrantCeiling(
                authority_issuer="https://issuer.example",
                namespace_id="tenant-a",
                allowed_references=GRANTED_REFS,
            )
        }
    )
    app = create_app(
        str(tmp_path / "api.sqlite"),
        settings=_settings(),
        stores=stores,
        agent_registry=registry,
        publisher_grants=grants,
        publication_security_revocation_actors=frozenset({"publisher-b"}),
    )
    adapter = RouteAdapter(app)
    definition_id = str(AgentDefinitionId(uuid4()))
    payload = _publish_payload(registry, adapter, definition_id)
    published = _post(
        adapter,
        f"/agent-definitions/{definition_id}/release",
        payload,
        host_context=_host_context(),
    )
    assert published.status_code == 201
    revoked = _post(
        adapter,
        f"/agent-definitions/{definition_id}/release/revoke",
        {
            "environment": "production",
            "reason_class": "security",
            "enforcement_mode": "immediate",
        },
        host_context=_host_context(),
    )
    assert revoked.status_code == 200
    assert revoked.body["status"] == "revoked"
    assert revoked.body["enforcement_mode"] == "immediate"
    scope = _scope_of(registry, definition_id)
    assert registry.resolve_published(scope, environment="production") is None
