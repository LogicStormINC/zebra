"""Mount+bind shares existing credentials, policy and safe retry semantics."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.client_capabilities import ProfileLifecycle

from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn
from tests.api.test_client_runtime_api import _api, _bundle, _handle, _profile

native_client_dsn = checkpoint_dsn


def surface():
    bundle = _bundle()
    profile = _profile()
    bundle.frontend_capabilities.publish_profile(profile)
    api = _api(bundle)
    opened = _handle(
        api,
        "POST",
        "/v1/client-sessions",
        body={
            "grant": {
                "grant_id": str(uuid4()),
                "host_app_id": "fixture-host",
                "namespace_id": "tenant-1",
                "frontend_app_id": profile.frontend_app_id,
                "origin": "https://app.fixture.example",
                "user_ref": "user-1",
                "profile_digest": profile.profile_digest,
                "scopes": ["client.action"],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        },
    )
    assert opened.status_code == 201
    session = opened.body["client_session_id"]
    headers = {"X-Zebra-Client-Session": opened.body["session_credential"]}
    body = {
        "mount": {
            "client_session_id": session,
            "frontend_app_id": profile.frontend_app_id,
            "profile_revision": 1,
            "profile_digest": profile.profile_digest,
            "mounted_readables": [],
            "mounted_actions": ["app.ui.item.open"],
            "ui_revision": 1,
            "mounted_at": datetime.now(UTC).isoformat(),
        },
        "task_capability_scope": ["app.ui.item.open"],
        "controller": True,
    }
    path = f"/v1/tasks/{uuid4()}/runs/fixture-run/client-surface"
    return api, bundle, session, headers, body, path


def test_composite_and_original_paths_have_same_logical_admission():
    api, bundle, session, headers, body, path = surface()
    first = _handle(api, "POST", path, body=body, headers=headers)
    assert first.status_code == 201, first.body
    assert first.body["allowed_actions"] == ["app.ui.item.open"]
    assert first.body["controller"] is True
    assert (
        first.body["mounted_snapshot_digest"]
        == bundle.client_sessions.snapshots[session].snapshot_digest
    )
    assert len(bundle.client_sessions.sessions) == len(bundle.client_sessions.bindings) == 1
    assert "session_credential" not in first.body
    original_mount = _handle(
        api, "POST", f"/v1/client-sessions/{session}/mount", body=body["mount"], headers=headers
    )
    original_bind = _handle(
        api,
        "POST",
        path.replace("client-surface", "client-bindings"),
        body={k: v for k, v in body.items() if k != "mount"},
        headers=headers,
    )
    for key in ("binding_id", "binding_digest", "binding_revision", "allowed_actions"):
        assert original_bind.body[key] == first.body[key]
    assert original_mount.body["mounted_snapshot_digest"] == first.body["mounted_snapshot_digest"]


def test_lost_response_retry_reuses_session_binding_and_rotates_fence():
    api, bundle, _, headers, body, path = surface()
    first = _handle(api, "POST", path, body=body, headers=headers)
    assert first.status_code == 201, first.body
    retry = _handle(api, "POST", path, body=body, headers=headers)
    assert retry.status_code == 201
    assert retry.body["binding_id"] == first.body["binding_id"]
    assert retry.body["binding_digest"] == first.body["binding_digest"]
    assert retry.body["controller_fence_token"] != first.body["controller_fence_token"]
    from hashlib import sha256

    assert (
        bundle.client_control_leases._lease.fence_hash
        == sha256(retry.body["controller_fence_token"].encode()).hexdigest()
    )
    assert (
        bundle.client_control_leases._lease.fence_hash
        != sha256(first.body["controller_fence_token"].encode()).hexdigest()
    )
    assert len(bundle.client_sessions.sessions) == len(bundle.client_sessions.bindings) == 1


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "controller",
        "scope",
        "too_many",
        "session",
        "profile",
        "revision",
        "mount_extra",
        "run",
        "task",
    ],
)
def test_invalid_composite_does_not_mount_or_bind(change):
    api, bundle, _, headers, body, path = surface()
    if change == "extra":
        body["unknown"] = True
    elif change == "controller":
        body["controller"] = "true"
    elif change == "scope":
        body["task_capability_scope"] = "app.ui.item.open"
    elif change == "too_many":
        body["task_capability_scope"] = ["app.ui.item.open"] * 129
    elif change == "session":
        body["mount"]["client_session_id"] = str(uuid4())
    elif change == "profile":
        body["mount"]["profile_digest"] = "a" * 64
    elif change == "revision":
        body["mount"]["profile_revision"] = 99
    elif change == "mount_extra":
        body["mount"]["unknown"] = True
    elif change == "run":
        path = path.replace("fixture-run", "r" * 129)
    elif change == "task":
        path = path.replace(path.split("/")[3], "not-a-uuid")
    response = _handle(api, "POST", path, body=body, headers=headers)
    assert response.status_code in {400, 403, 409}, response.body
    assert bundle.client_sessions.snapshots == bundle.client_sessions.bindings == {}


@pytest.mark.parametrize("mode", ["missing", "wrong", "expired", "revoked"])
def test_existing_client_and_current_profile_authority_remain_required(mode):
    api, bundle, session, headers, body, path = surface()
    if mode == "missing":
        headers = {}
    if mode == "wrong":
        headers["X-Zebra-Client-Session"] = f"{session}:wrong-session-secret"
    if mode == "expired":
        bundle.client_sessions.sessions[session] = bundle.client_sessions.sessions[
            session
        ].model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    if mode == "revoked":
        profile = _profile()
        bundle.frontend_capabilities.set_lifecycle(
            profile.frontend_app_id, 1, ProfileLifecycle.REVOKED
        )
    response = _handle(api, "POST", path, body=body, headers=headers)
    assert response.status_code in {401, 409}, response.body
    assert bundle.client_sessions.snapshots == bundle.client_sessions.bindings == {}


def test_bind_failure_retains_partial_state_and_retry_can_finish(monkeypatch):
    from agent_core.domain.client_sessions import ClientControlLeaseError

    api, bundle, session, headers, body, path = surface()
    claim = bundle.client_control_leases.claim_controller
    monkeypatch.setattr(
        bundle.client_control_leases,
        "claim_controller",
        lambda *a, **kw: (_ for _ in ()).throw(ClientControlLeaseError("conflict")),
    )
    response = _handle(api, "POST", path, body=body, headers=headers)
    assert response.status_code == 409, response.body
    assert session in bundle.client_sessions.snapshots
    assert len(bundle.client_sessions.sessions) == 1
    monkeypatch.setattr(bundle.client_control_leases, "claim_controller", claim)
    retry = _handle(api, "POST", path, body=body, headers=headers)
    assert retry.status_code == 201
    assert len(bundle.client_sessions.bindings) == 1


def test_capability_is_advertised_only_with_complete_client_stores():
    api, _, _, _, _, _ = surface()
    response = _handle(api, "GET", "/capabilities/runtime")
    assert response.body["client_surface_contract_version"] == 1
    assert (
        _handle(_api(None), "GET", "/capabilities/runtime").body["client_surface_contract_version"]
        == 0
    )


@pytest.mark.parametrize("mismatch", [None, "run", "thread", "issuer", "uuid"])
def test_exact_composite_target_precedes_nonce_consumption(mismatch):
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace

    from agent_core.domain.host_authority import HostResourceRef

    from tests.api.test_http_host_preflight import Authorizer, authorize, request_for
    from tests.api.test_task_resource_binding import TASK, binding_for, verified
    from tests.host_grant_broker.test_grant_broker import _key, _settings

    key = _key()
    grant = verified((key, _settings(key)), run="request-run")
    incoming = grant
    path = f"/v1/tasks/{TASK}/runs/request-run/client-surface"
    if mismatch == "run":
        path = path.replace("request-run", "foreign")
    if mismatch == "uuid":
        path = path.replace(TASK, "not-a-uuid")
    if mismatch == "issuer":
        incoming = replace(grant, authority_issuer="https://foreign.test")
    if mismatch == "thread":
        incoming = replace(
            grant,
            context=grant.context.model_copy(
                update={
                    "resource_refs": tuple(
                        HostResourceRef(type="thread", id="foreign")
                        if ref.resource_type == "thread"
                        else ref
                        for ref in grant.context.resource_refs
                    )
                }
            ),
        )
    authorizer = Authorizer(incoming)
    api = SimpleNamespace(
        stores=SimpleNamespace(deployment_namespace="scratch"),
        cloud_control=SimpleNamespace(
            deployment_namespace="scratch", load_task_binding=lambda _: binding_for(grant)
        ),
    )
    response = asyncio.run(authorize(request_for(path, method="POST"), api, authorizer))
    if mismatch is None:
        assert response is None and authorizer.consumed == [path]
    else:
        assert response.status_code in {400, 404}
        assert authorizer.consumed == []


@pytest.mark.parametrize("mismatch", [None, "thread", "run", "issuer", "unverified"])
def test_direct_dispatch_rechecks_task_authority_before_mutations(mismatch):
    from dataclasses import replace
    from types import SimpleNamespace

    from zebra_agent_api.client_runtime_routes import handle_client_runtime_route
    from zebra_agent_api.routes import RouteRequest

    from tests.api.test_task_resource_binding import TASK, app_for, binding_for, verified
    from tests.host_grant_broker.test_grant_broker import _key, _settings

    _, bundle, session, headers, body, _ = surface()
    key = _key()
    broker = (key, _settings(key))
    grant = verified(broker, run="fixture-run")
    saved = bundle.client_sessions.sessions[session]
    bundle.client_sessions.sessions[session] = saved.model_copy(
        update={
            "grant": saved.grant.model_copy(
                update={
                    "host_app_id": grant.context.host_app_id,
                    "namespace_id": grant.context.namespace_id,
                    "origin": grant.context.origin,
                }
            )
        }
    )
    app = app_for(binding_for(grant))
    app.settings = SimpleNamespace(deployment="cloud")
    app.client_platform = bundle
    app.stores.tasks = SimpleNamespace(get_task=lambda _: SimpleNamespace(active_segment_id=TASK))
    incoming = grant
    if mismatch == "thread":
        incoming = verified(broker, thread="foreign", run="fixture-run")
    if mismatch == "run":
        incoming = verified(broker, run="foreign")
    if mismatch == "issuer":
        incoming = replace(grant, authority_issuer="https://foreign.test")
    response = handle_client_runtime_route(
        app,
        RouteRequest(
            "POST",
            f"/v1/tasks/{TASK}/runs/fixture-run/client-surface",
            body=body,
            headers=headers,
            host_context=incoming.context,
            verified_host_grant=None if mismatch == "unverified" else incoming,
        ),
    )
    assert response.status_code == (
        201 if mismatch is None else 403 if mismatch == "unverified" else 404
    )
    if mismatch is not None:
        assert bundle.client_sessions.snapshots == bundle.client_sessions.bindings == {}


def test_native_response_loss_stale_fence_and_competing_clients(native_client_dsn, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from uuid import UUID

    from agent_core.domain.client_sessions import ClientControlFence, ClientFenceError
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.client_control_leases import PostgresClientControlLeaseStore
    from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry

    from tests.worker import test_model_commentary_native as native

    monkeypatch.setattr(native, "NS", "client-surface-" + uuid4().hex)
    state = native.native_state(native_client_dsn)
    task_id = state.tasks.ensure_for_session(state.session.session_id).task_id
    api, fake, session, headers, body, _ = surface()
    sessions = PostgresClientSessionRegistry(native_client_dsn, deployment_namespace=native.NS)
    leases = PostgresClientControlLeaseStore(native_client_dsn, deployment_namespace=native.NS)
    sessions.create_session(fake.client_sessions.sessions[session])
    api = replace(
        api, client_platform=replace(fake, client_sessions=sessions, client_control_leases=leases)
    )
    path = f"/v1/tasks/{task_id}/runs/fixture-run/client-surface"
    first = _handle(api, "POST", path, body=body, headers=headers)
    retry = _handle(api, "POST", path, body=body, headers=headers)
    assert first.status_code == retry.status_code == 201, (first.body, retry.body)
    assert first.body["binding_id"] == retry.body["binding_id"]
    args = dict(task_id=TaskId(task_id), run_id="fixture-run", ttl=timedelta(seconds=60))
    with pytest.raises(ClientFenceError):
        leases.renew(
            UUID(first.body["binding_id"]),
            fence=ClientControlFence(token=first.body["controller_fence_token"]),
            **args,
        )
    leases.renew(
        UUID(retry.body["binding_id"]),
        fence=ClientControlFence(token=retry.body["controller_fence_token"]),
        **args,
    )

    # Two different tabs race on a fresh Run: exactly one controller may win.
    _, other, second, headers2, body2, _ = surface()
    sessions.create_session(other.client_sessions.sessions[second])
    competing_path = path.replace("fixture-run", "competing-run")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: _handle(api, "POST", competing_path, headers=pair[0], body=pair[1]),
                [(headers, body), (headers2, body2)],
            )
        )
    assert sorted(r.status_code for r in results) == [201, 409], [r.body for r in results]
    with state.database.connect() as connection:
        row = connection.execute(
            "SELECT count(*) AS n FROM client_control_leases "
            "WHERE deployment_namespace=%s AND task_id=%s AND run_id='competing-run'",
            (native.NS, task_id),
        ).fetchone()
    assert row["n"] == 1


def test_client_composition_reuses_existing_bounded_resolver():
    from agent_storage.postgres.task_io import TaskIoConnections
    from zebra_agent_api.platform_composition import compose_api_platform_control_plane

    dsn = "postgresql://fixture@localhost:5432/fixture"
    shared = TaskIoConnections(dsn)
    bundle = compose_api_platform_control_plane(
        dsn,
        deployment_namespace="fixture",
        client_integration_enabled=True,
        task_io_connections=shared,
    )
    for adapter in (
        bundle.frontend_capabilities,
        bundle.client_sessions,
        bundle.client_control_leases,
    ):
        assert adapter._database._task_io is shared
    with pytest.raises(ValueError, match="configuration does not match"):
        compose_api_platform_control_plane(
            dsn + "_foreign",
            deployment_namespace="fixture",
            client_integration_enabled=True,
            task_io_connections=shared,
        )
