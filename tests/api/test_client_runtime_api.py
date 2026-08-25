"""Client runtime + management API acceptance with fake platform stores."""

from __future__ import annotations

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
        candidates = sorted(
            (rev for aid, rev in self.profiles if aid == app_id), reverse=True
        )
        return self.profiles.get((app_id, candidates[0])) if candidates else None

    def set_lifecycle(self, app_id: str, revision: int, lifecycle) -> None:
        profile = self.profiles.get((app_id, revision))
        if profile is None:
            raise ValueError("not found")
        order = {"published": 0, "deprecated": 1, "revoked": 2}
        if order[lifecycle.value] <= order[profile.lifecycle.value]:
            raise ValueError("lifecycle only moves forward")
        self.profiles[(app_id, revision)] = profile.model_copy(
            update={"lifecycle": lifecycle}
        )

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


def _api(bundle: AgentPlatformControlPlane | None, *, operator_token=None):
    from zebra_agent_api.app import ZebraAgentApi

    settings = _settings()
    return ZebraAgentApi(
        database_path="/tmp/zebra-client-api-test.sqlite",
        settings=settings,
        client_platform=bundle,
        platform_operator_authorizer=(
            StaticTokenPlatformOperatorAuthorizer(operator_token, strict=False)
            if operator_token
            else None
        ),
    )


def _handle(api, method: str, path: str, *, body=None, headers=None):
    from zebra_agent_api.routes import RouteAdapter, RouteRequest

    adapter = RouteAdapter(api)
    return adapter.handle(
        RouteRequest(method=method, path=path, body=body, headers=headers)
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
        api, "GET", "/platform/v1/frontend-profiles/fixture-web",
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


def test_client_session_open_mount_and_bind() -> None:
    bundle = _bundle()
    api = _api(bundle)
    grant = {
        "grant_id": str(uuid4()),
        "host_app_id": "fixture-host",
        "namespace_id": "tenant-1",
        "frontend_app_id": "fixture-web",
        "origin": "https://app.fixture.example",
        "user_ref": "user-1",
        "profile_digest": "a" * 64,
        "scopes": ["client.action"],
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    opened = _handle(api, "POST", "/v1/client-sessions", body={"grant": grant})
    assert opened.status_code == 201
    session_id = opened.body["client_session_id"]
    profile = _profile()
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
        headers={"Authorization": f"Bearer {session_id}:fence-token-value"},
    )
    assert mounted.status_code == 200
    task_id = new_task_id()
    bound = _handle(
        api,
        "POST",
        f"/v1/tasks/{task_id}/runs/run-1/client-bindings",
        body={"task_capability_scope": ["app.ui.item.open"]},
        headers={"Authorization": f"Bearer {session_id}:fence-token-value"},
    )
    assert bound.status_code == 201
    assert bound.body["allowed_actions"] == ["app.ui.item.open"]
    assert bound.body["controller"] is True
