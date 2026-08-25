"""Client runtime + management API acceptance with fake platform stores."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent_core.domain.client_capabilities import (
    ClientActionContract,
    ClientActionRisk,
    ClientReadableContract,
    FrontendCapabilityProfileVersion,
    MountedCapabilitySnapshot,
)
from agent_core.domain.client_sessions import (
    ClientSession,
)
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import new_task_id
from agent_core.ports.platform_control_plane import AgentPlatformControlPlane
from zebra_agent_api.platform_operator_auth import (
    StaticTokenPlatformOperatorAuthorizer,
)
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.settings import ApiSettings, ModelSettings


def _settings() -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url="/tmp/zebra-client-api-test.sqlite",
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


class FakeCapabilityRegistry:
    deployment_namespace = "test-ns"

    def __init__(self) -> None:
        self.profiles: dict[tuple[str, int], FrontendCapabilityProfileVersion] = {}
        self.bindings: dict[str, object] = {}
        self._binding_revisions: dict[str, int] = {}

    def publish_profile(self, profile: FrontendCapabilityProfileVersion) -> None:
        from agent_core.domain.client_capabilities import (
            ClientCapabilityError,
            validate_profile_for_publish,
        )

        validate_profile_for_publish(profile)
        existing = self.profiles.get((profile.frontend_app_id, profile.revision))
        if existing is not None:
            if existing.profile_digest != profile.profile_digest:
                raise ClientCapabilityError("revision digest mismatch")
            return
        self.profiles[(profile.frontend_app_id, profile.revision)] = profile

    def get_profile(self, app_id: str, revision: int):
        return self.profiles.get((app_id, revision))

    def get_latest_profile(self, app_id: str):
        candidates = sorted((rev for aid, rev in self.profiles if aid == app_id), reverse=True)
        return self.profiles.get((app_id, candidates[0])) if candidates else None

    def get_profile_by_digest(self, app_id: str, profile_digest: str):
        return next(
            (
                profile
                for (candidate_app_id, _), profile in self.profiles.items()
                if candidate_app_id == app_id and profile.profile_digest == profile_digest
            ),
            None,
        )

    def set_lifecycle(self, app_id: str, revision: int, lifecycle) -> None:
        profile = self.profiles.get((app_id, revision))
        if profile is None:
            raise ValueError("not found")
        order = {"published": 0, "deprecated": 1, "revoked": 2}
        if order[lifecycle.value] <= order[profile.lifecycle.value]:
            raise ValueError("lifecycle only moves forward")
        self.profiles[(app_id, revision)] = profile.model_copy(update={"lifecycle": lifecycle})

    def save_binding(self, binding, *, expected_binding_revision: int):
        key = str(binding.binding_id)
        current = self._binding_revisions.get(key)
        if current is not None and current != expected_binding_revision:
            raise ValueError("CAS stale")
        self._binding_revisions[key] = binding.binding_revision
        self.bindings[key] = binding
        return binding

    def get_binding(self, binding_id):
        return self.bindings.get(str(binding_id))

    def get_binding_for_host(self, host_app_id, namespace_id, frontend_app_id):
        return next(
            (
                binding
                for binding in self.bindings.values()
                if binding.host_app_id == host_app_id
                and binding.namespace_id == namespace_id
                and binding.frontend_app_id == frontend_app_id
            ),
            None,
        )


class FakeSessionRegistry:
    deployment_namespace = "test-ns"

    def __init__(self) -> None:
        self.sessions: dict[str, ClientSession] = {}
        self.snapshots: dict[str, MountedCapabilitySnapshot] = {}
        self.bindings: dict[tuple, object] = {}

    def create_session(self, session: ClientSession) -> None:
        self.sessions.setdefault(str(session.session_id), session)

    def get_session(self, session_id):
        return self.sessions.get(str(session_id))

    def heartbeat_session(self, session_id, *, heartbeat_at):
        session = self.sessions[str(session_id)]
        session.ensure_renewable(now=heartbeat_at)
        return session

    def close_session(self, session_id) -> None:
        self.sessions.pop(str(session_id), None)

    def save_mounted_snapshot(self, snapshot) -> None:
        self.snapshots[str(snapshot.client_session_id)] = snapshot

    def get_mounted_snapshot(self, client_session_id):
        return self.snapshots.get(str(client_session_id))

    def save_run_binding(self, binding) -> None:
        key = (str(binding.task_id), binding.run_id, str(binding.client_session_id))
        existing = self.bindings.get(key)
        if existing is not None and binding.binding_revision < existing.binding_revision:
            raise ValueError("revisions only increase")
        self.bindings[key] = binding

    def get_run_binding(self, task_id, run_id, client_session_id):
        return self.bindings.get((str(task_id), run_id, str(client_session_id)))

    def get_active_run_binding(self, task_id):
        matches = [
            binding
            for (candidate_task_id, _, _), binding in self.bindings.items()
            if candidate_task_id == str(task_id)
        ]
        return matches[0] if len(matches) == 1 else None


class FakeControlLeaseStore:
    deployment_namespace = "test-ns"

    def __init__(self) -> None:
        self._lease = None

    def claim_controller(self, run_binding_id, *, task_id, run_id, client_session_id, fence, ttl):
        from agent_core.domain.client_sessions import (
            ClientControlLease,
            ClientControlLeaseError,
        )

        if self._lease is not None and not self._lease.is_expired():
            if self._lease.client_session_id != client_session_id:
                raise ClientControlLeaseError("another tab holds the lease")
        now = datetime.now(UTC)
        self._lease = ClientControlLease(
            run_binding_id=run_binding_id,
            client_session_id=client_session_id,
            fence_hash=fence.fence_hash,
            acquired_at=now,
            heartbeat_at=now,
            expires_at=now + ttl,
        )
        return self._lease

    def renew(self, run_binding_id, *, task_id, run_id, fence, ttl):
        from agent_core.domain.client_sessions import ClientFenceError

        if self._lease is None or not self._lease.matches_fence(fence):
            raise ClientFenceError("stale fence")
        return self._lease

    def release(self, run_binding_id, *, task_id, run_id, fence) -> None:
        self._lease = None

    def get_active(self, run_binding_id):
        return self._lease


def _profile() -> FrontendCapabilityProfileVersion:
    return FrontendCapabilityProfileVersion(
        frontend_app_id="fixture-web",
        revision=1,
        readables=(ClientReadableContract(name="app.ui.route"),),
        actions=(
            ClientActionContract(
                name="app.ui.item.open",
                risk=ClientActionRisk.PRESENTATION,
            ),
        ),
        published_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


def _bundle() -> AgentPlatformControlPlane:
    return AgentPlatformControlPlane(
        deployment_namespace="test-ns",
        frontend_capabilities=FakeCapabilityRegistry(),
        client_sessions=FakeSessionRegistry(),
        client_control_leases=FakeControlLeaseStore(),
    )


def _api(
    bundle: AgentPlatformControlPlane | None,
    *,
    operator_token=None,
    profile: str = "test",
):
    from agent_storage import sqlite_control_plane_stores
    from zebra_agent_api.app import ZebraAgentApi

    settings = replace(_settings(), profile=profile)
    return ZebraAgentApi(
        database_path="/tmp/zebra-client-api-test.sqlite",
        settings=settings,
        _stores=(
            sqlite_control_plane_stores("/tmp/zebra-client-api-test.sqlite")
            if profile == "cloud"
            else None
        ),
        client_platform=bundle,
        platform_operator_authorizer=(
            StaticTokenPlatformOperatorAuthorizer(operator_token, strict=False)
            if operator_token
            else None
        ),
    )


def _handle(api, method: str, path: str, *, body=None, headers=None, host_context=None):
    from zebra_agent_api.routes import RouteAdapter, RouteRequest

    adapter = RouteAdapter(api)
    return adapter.handle(
        RouteRequest(
            method=method,
            path=path,
            body=body,
            headers=headers,
            host_context=host_context,
        )
    )


def test_management_routes_require_operator_token() -> None:
    api = _api(_bundle())
    response = _handle(
        api, "POST", "/platform/v1/frontend-profiles", body=_profile().model_dump(mode="json")
    )
    assert response.status_code in {401, 503}
    assert response.body.get("status") in {"unauthorized", "unavailable"}


def test_publish_and_retrieve_profile_as_operator() -> None:
    api = _api(_bundle(), operator_token="op-token")
    body = _profile().model_dump(mode="json")
    created = _handle(
        api,
        "POST",
        "/platform/v1/frontend-profiles",
        body=body,
        headers={"Authorization": "Bearer op-token"},
    )
    assert created.status_code == 201
    fetched = _handle(
        api,
        "GET",
        "/platform/v1/frontend-profiles/fixture-web",
        headers={"Authorization": "Bearer op-token"},
    )
    assert fetched.status_code == 200
    assert fetched.body["revision"] == 1


def test_disabled_integration_fails_closed() -> None:
    api = _api(None, operator_token="op-token")
    response = _handle(
        api,
        "GET",
        "/platform/v1/frontend-profiles/fixture-web",
        headers={"Authorization": "Bearer op-token"},
    )
    assert response.status_code == 503
    assert response.body.get("code") == "client_integration_disabled"


def test_cloud_client_session_open_requires_verified_host_context() -> None:
    bundle = _bundle()
    profile = _profile()
    assert bundle.frontend_capabilities is not None
    bundle.frontend_capabilities.publish_profile(profile)
    response = _handle(
        _api(bundle, profile="cloud"),
        "POST",
        "/v1/client-sessions",
        body={"grant": {}},
    )
    assert response.status_code == 401
    assert response.body["reason"] == "verified_host_context_required"


def test_client_session_open_mount_and_bind() -> None:
    bundle = _bundle()
    api = _api(bundle)
    profile = _profile()
    assert bundle.frontend_capabilities is not None
    bundle.frontend_capabilities.publish_profile(profile)
    grant = {
        "grant_id": str(uuid4()),
        "host_app_id": "fixture-host",
        "namespace_id": "tenant-1",
        "frontend_app_id": "fixture-web",
        "origin": "https://app.fixture.example",
        "user_ref": "user-1",
        "profile_digest": profile.profile_digest,
        "scopes": ["client.action"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    opened = _handle(api, "POST", "/v1/client-sessions", body={"grant": grant})
    assert opened.status_code == 201
    session_id = opened.body["client_session_id"]
    session_credential = opened.body["session_credential"]
    heartbeat = _handle(
        api,
        "POST",
        f"/v1/client-sessions/{session_id}/heartbeat",
        headers={"X-Zebra-Client-Session": session_credential},
    )
    assert heartbeat.status_code == 200
    host_grant_slot_is_not_a_session_credential = _handle(
        api,
        "POST",
        f"/v1/client-sessions/{session_id}/heartbeat",
        headers={"Authorization": f"Bearer {session_credential}"},
    )
    assert host_grant_slot_is_not_a_session_credential.status_code == 401
    rejected = _handle(
        api,
        "POST",
        f"/v1/client-sessions/{session_id}/heartbeat",
        headers={"X-Zebra-Client-Session": f"{session_id}:not-the-session-secret"},
    )
    assert rejected.status_code == 401
    crossed = _handle(
        api,
        "POST",
        f"/v1/client-sessions/{uuid4()}/heartbeat",
        headers={"X-Zebra-Client-Session": session_credential},
    )
    assert crossed.status_code == 403
    snapshot = MountedCapabilitySnapshot(
        client_session_id=uuid4(),
        frontend_app_id="fixture-web",
        profile_revision=1,
        profile_digest=profile.profile_digest,
        mounted_actions=("app.ui.item.open",),
        ui_revision=1,
        mounted_at=datetime.now(UTC),
    )
    from uuid import UUID as _UUID

    snapshot = snapshot.model_copy(update={"client_session_id": _UUID(session_id)})
    mounted = _handle(
        api,
        "POST",
        f"/v1/client-sessions/{session_id}/mount",
        body=snapshot.model_dump(mode="json"),
        headers={"X-Zebra-Client-Session": session_credential},
    )
    assert mounted.status_code == 200
    task_id = new_task_id()
    invalid_scope = _handle(
        api,
        "POST",
        f"/v1/tasks/{task_id}/runs/run-1/client-bindings",
        body={"task_capability_scope": "app.ui.item.open"},
        headers={"X-Zebra-Client-Session": session_credential},
    )
    assert invalid_scope.status_code == 400
    invalid_controller = _handle(
        api,
        "POST",
        f"/v1/tasks/{task_id}/runs/run-1/client-bindings",
        body={"task_capability_scope": [], "controller": "false"},
        headers={"X-Zebra-Client-Session": session_credential},
    )
    assert invalid_controller.status_code == 400
    bound = _handle(
        api,
        "POST",
        f"/v1/tasks/{task_id}/runs/run-1/client-bindings",
        body={"task_capability_scope": ["app.ui.item.open"]},
        headers={"X-Zebra-Client-Session": session_credential},
    )
    assert bound.status_code == 201
    assert bound.body["allowed_actions"] == ["app.ui.item.open"]
    assert bound.body["controller"] is True
    assert len(bound.body["controller_fence_token"]) >= 16
    controller = {
        "task_id": str(task_id),
        "run_id": "run-1",
        "run_binding_id": bound.body["binding_id"],
    }
    renewed = _handle(
        api,
        "POST",
        f"/v1/client-sessions/{session_id}/heartbeat",
        body=controller,
        headers={
            "X-Zebra-Client-Session": session_credential,
            "X-Zebra-Client-Fence": bound.body["controller_fence_token"],
        },
    )
    assert renewed.status_code == 200
    assert renewed.body["controller_expires_at"] is not None
    released = _handle(
        api,
        "POST",
        f"/v1/client-sessions/{session_id}/release",
        body=controller,
        headers={
            "X-Zebra-Client-Session": session_credential,
            "X-Zebra-Client-Fence": bound.body["controller_fence_token"],
        },
    )
    assert released.status_code == 200
    stale = _handle(
        api,
        "POST",
        f"/v1/client-sessions/{session_id}/heartbeat",
        body=controller,
        headers={
            "X-Zebra-Client-Session": session_credential,
            "X-Zebra-Client-Fence": bound.body["controller_fence_token"],
        },
    )
    assert stale.status_code == 409


def test_expired_client_grant_never_creates_a_session() -> None:
    bundle = _bundle()
    profile = _profile()
    assert bundle.frontend_capabilities is not None
    bundle.frontend_capabilities.publish_profile(profile)
    response = _handle(
        _api(bundle),
        "POST",
        "/v1/client-sessions",
        body={
            "grant": {
                "grant_id": str(uuid4()),
                "host_app_id": "fixture-host",
                "namespace_id": "tenant-1",
                "frontend_app_id": "fixture-web",
                "origin": "https://app.fixture.example",
                "user_ref": "user-1",
                "profile_digest": profile.profile_digest,
                "scopes": ["client.action"],
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
        },
    )
    assert response.status_code == 409
    assert bundle.client_sessions is not None
    assert bundle.client_sessions.sessions == {}


def test_malformed_client_boundaries_return_400_instead_of_raising() -> None:
    bundle = _bundle()
    profile = _profile()
    assert bundle.frontend_capabilities is not None
    bundle.frontend_capabilities.publish_profile(profile)
    api = _api(bundle)
    invalid_grant = _handle(api, "POST", "/v1/client-sessions", body={"grant": {}})
    assert invalid_grant.status_code == 400

    opened = _handle(
        api,
        "POST",
        "/v1/client-sessions",
        body={
            "grant": {
                "grant_id": str(uuid4()),
                "host_app_id": "fixture-host",
                "namespace_id": "tenant-1",
                "frontend_app_id": "fixture-web",
                "origin": "https://app.fixture.example",
                "user_ref": "user-1",
                "profile_digest": profile.profile_digest,
                "scopes": ["client.action"],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        },
    )
    credential = opened.body["session_credential"]
    headers = {"X-Zebra-Client-Session": credential}
    assert (
        _handle(
            api,
            "POST",
            "/v1/client-sessions/not-a-uuid/heartbeat",
            headers=headers,
        ).status_code
        == 400
    )
    assert (
        _handle(
            api,
            "GET",
            "/v1/client-effects/not-a-uuid",
            headers=headers,
        ).status_code
        == 400
    )


def test_host_authenticated_open_requires_the_namespace_profile_binding() -> None:
    from agent_control_plane.frontend_profiles import FrontendProfileService

    bundle = _bundle()
    profile = _profile()
    registry = bundle.frontend_capabilities
    assert registry is not None
    registry.publish_profile(profile)
    context = HostContextEnvelope(
        grant_id="host-grant-1",
        host_app_id="fixture-host",
        namespace_id="tenant-1",
        workspace_ref="workspace://fixture",
        resource_refs=(HostResourceRef(type="fixture.item", id="item-1"),),
        scopes=("session.write",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=600,
            max_model_tokens=10_000,
            max_artifact_bytes=1_000_000,
        ),
        origin="https://app.fixture.example",
        policy_version="fixture-policy-v1",
    )
    grant = {
        "grant_id": str(uuid4()),
        "host_app_id": context.host_app_id,
        "namespace_id": context.namespace_id,
        "frontend_app_id": profile.frontend_app_id,
        "origin": context.origin,
        "user_ref": "user-1",
        "profile_digest": profile.profile_digest,
        "scopes": ["client.action"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    api = _api(bundle, profile="cloud")
    denied = _handle(
        api,
        "POST",
        "/v1/client-sessions",
        body={"grant": grant},
        host_context=context,
    )
    assert denied.status_code == 403
    FrontendProfileService(registry).bind(
        host_app_id=context.host_app_id,
        namespace_id=context.namespace_id,
        frontend_app_id=profile.frontend_app_id,
        revision=profile.revision,
        profile_digest=profile.profile_digest,
    )
    opened = _handle(
        api,
        "POST",
        "/v1/client-sessions",
        body={"grant": grant},
        host_context=context,
    )
    assert opened.status_code == 201
    session_id = opened.body["client_session_id"]
    credential = opened.body["session_credential"]
    headers = {"X-Zebra-Client-Session": credential}
    assert (
        _handle(
            api,
            "POST",
            f"/v1/client-sessions/{session_id}/heartbeat",
            headers=headers,
        ).status_code
        == 401
    )
    assert (
        _handle(
            api,
            "POST",
            f"/v1/client-sessions/{session_id}/heartbeat",
            headers=headers,
            host_context=context,
        ).status_code
        == 200
    )
    crossed_context = context.model_copy(update={"namespace_id": "tenant-2"})
    assert (
        _handle(
            api,
            "POST",
            f"/v1/client-sessions/{session_id}/heartbeat",
            headers=headers,
            host_context=crossed_context,
        ).status_code
        == 401
    )
