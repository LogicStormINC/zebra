"""One explicit Cloud callback owner; original fresh checks remain inside it."""

from dataclasses import replace

import pytest
from agent_storage.postgres.connection_scope import current_connection_scope
from agent_storage.postgres.task_io import current_task_io_deadline
from zebra_agent_api import client_surface
from zebra_agent_api.client_runtime_routes import handle_client_runtime_route

from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn
from tests.api.test_client_surface_open import opening

native_client_dsn = checkpoint_dsn


@pytest.mark.parametrize("authenticated", [False, True])
def test_each_cloud_surface_owns_and_closes_its_bounded_connection_scope(
    monkeypatch, authenticated
):
    app, _, request = opening()
    if authenticated:
        opened = handle_client_runtime_route(app, request)
        assert opened.status_code == 201
        request = replace(
            request,
            headers={"X-Zebra-Client-Session": opened.body["session_credential"]},
            body={
                "mount": {
                    **request.body["mount"],
                    "client_session_id": opened.body["client_session_id"],
                },
                **{key: request.body[key] for key in ("task_capability_scope", "controller")},
            },
        )
    seen = []
    for name in ("task_access_response", "mount_client_session", "bind_client_run"):
        original = getattr(client_surface, name)

        def measured(*args, original=original, **kwargs):
            owner = current_connection_scope()
            assert owner is not None and owner.bounded_deadline == current_task_io_deadline()
            seen.append(owner)
            return original(*args, **kwargs)

        monkeypatch.setattr(client_surface, name, measured)
    assert handle_client_runtime_route(app, request).status_code == 201
    assert len(seen) == 3 and all(owner is seen[0] for owner in seen)
    assert seen[0].closed and current_connection_scope() is None
    previous = seen[0]
    seen.clear()
    assert handle_client_runtime_route(app, request).status_code == (201 if authenticated else 409)
    assert seen[0].closed and seen[0] is not previous


def test_scope_closes_when_a_partial_admission_raises(monkeypatch):
    app, _, request = opening()
    seen = []

    def failed(*args, **kwargs):
        owner = current_connection_scope()
        assert owner is not None
        seen.append(owner)
        raise RuntimeError("interrupted after open")

    monkeypatch.setattr(client_surface, "mount_client_session", failed)
    with pytest.raises(RuntimeError, match="interrupted after open"):
        handle_client_runtime_route(app, request)
    assert seen[0].closed and current_connection_scope() is None


def test_native_scoped_reads_observe_committed_revocation(native_client_dsn):
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic

    import psycopg
    from agent_core.domain.client_capabilities import ProfileLifecycle
    from agent_core.domain.client_sessions import ClientSessionStatus
    from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
    from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry
    from agent_storage.postgres.connection_scope import postgres_connection_scope
    from agent_storage.postgres.task_io import task_io_deadline

    from tests.api.test_client_surface import surface

    _, fake, session_id, _, _, _ = surface()
    sessions = PostgresClientSessionRegistry(native_client_dsn, deployment_namespace="scope-fresh")
    profiles = PostgresClientCapabilityRegistry(
        native_client_dsn, deployment_namespace="scope-fresh"
    )
    saved = fake.client_sessions.sessions[session_id]
    profile = next(iter(fake.frontend_capabilities.profiles.values()))
    sessions.create_session(saved)
    profiles.publish_profile(profile)

    def revoke():
        # Independent connection/transaction; no inherited scope or read cache.
        with psycopg.connect(native_client_dsn) as connection:
            connection.execute(
                "UPDATE client_sessions SET status='expired' "
                "WHERE deployment_namespace=%s AND client_session_id=%s",
                ("scope-fresh", session_id),
            )
        profiles.set_lifecycle(profile.frontend_app_id, profile.revision, ProfileLifecycle.REVOKED)

    with task_io_deadline(monotonic() + 2), postgres_connection_scope(bounded=True):
        assert sessions.get_session(saved.session_id).status is ClientSessionStatus.ACTIVE
        assert (
            profiles.get_profile(profile.frontend_app_id, profile.revision).lifecycle
            is ProfileLifecycle.PUBLISHED
        )
        with ThreadPoolExecutor(1) as pool:
            pool.submit(revoke).result(timeout=1.5)
        assert sessions.get_session(saved.session_id).status is ClientSessionStatus.EXPIRED
        assert (
            profiles.get_profile(profile.frontend_app_id, profile.revision).lifecycle
            is ProfileLifecycle.REVOKED
        )



def test_local_mount_keeps_original_connection_ownership(monkeypatch):
    from tests.api.test_client_runtime_api import _handle
    from tests.api.test_client_surface import surface

    app, _, _, headers, body, path = surface()
    seen = []
    original = client_surface.mount_client_session

    def mount(*args, **kwargs):
        seen.append(current_connection_scope())
        return original(*args, **kwargs)

    monkeypatch.setattr(client_surface, "mount_client_session", mount)
    assert app.settings.deployment == "local"
    assert _handle(app, "POST", path, body=body, headers=headers).status_code == 201
    assert seen == [None]
