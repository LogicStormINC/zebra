"""Real-PostgreSQL acceptance for client sessions and control leases (v32)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.client_capabilities import (
    ClientActionContract,
    ClientActionRisk,
    ClientReadableContract,
    FrontendCapabilityProfileVersion,
    MountedCapabilitySnapshot,
)
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLeaseError,
    ClientFenceError,
    ClientSession,
    ClientSessionExpiredError,
    ClientSessionGrant,
)
from agent_core.domain.identifiers import (
    new_client_run_binding_id,
    new_task_id,
)
from agent_storage.postgres.client_sessions import (
    PostgresClientControlLeaseStore,
    PostgresClientSessionRegistry,
)
from agent_storage.postgres.migration_runner import apply_postgres_migrations

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEBRA_TEST_POSTGRES_DSN"),
    reason="set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests",
)


@pytest.fixture()
def stores() -> tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str]:
    dsn = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    apply_postgres_migrations(dsn)
    namespace = f"client-session-{uuid4()}"
    return (
        PostgresClientSessionRegistry(dsn, deployment_namespace=namespace),
        PostgresClientControlLeaseStore(dsn, deployment_namespace=namespace),
        dsn,
        namespace,
    )


def _grant(**overrides) -> ClientSessionGrant:
    payload = {
        "grant_id": uuid4(),
        "host_app_id": "fixture-host",
        "namespace_id": "tenant-1",
        "frontend_app_id": "fixture-web",
        "origin": "https://app.fixture.example",
        "user_ref": "user-1",
        "profile_digest": "a" * 64,
        "scopes": ("client.action",),
        "expires_at": datetime.now(UTC) + timedelta(hours=2),
    }
    payload.update(overrides)
    return ClientSessionGrant.model_validate(payload)


def _session(**overrides) -> ClientSession:
    payload = {
        "grant": _grant(),
        "created_at": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + timedelta(hours=2),
    }
    payload.update(overrides)
    return ClientSession.model_validate(payload)


def test_two_tabs_claim_and_only_one_wins(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    sessions, leases, _, _ = stores
    tab_a = _session()
    tab_b = _session()
    sessions.create_session(tab_a)
    sessions.create_session(tab_b)
    task_id = new_task_id()
    fence_a = ClientControlFence.issue()
    fence_b = ClientControlFence.issue()
    lease = leases.claim_controller(
        new_client_run_binding_id(),
        task_id=task_id,
        run_id="run-1",
        client_session_id=tab_a.session_id,
        fence=fence_a,
        ttl=timedelta(minutes=5),
    )
    assert lease.matches_fence(fence_a)
    with pytest.raises(ClientControlLeaseError):
        leases.claim_controller(
            new_client_run_binding_id(),
            task_id=task_id,
            run_id="run-1",
            client_session_id=tab_b.session_id,
            fence=fence_b,
            ttl=timedelta(minutes=5),
        )
    # the incumbent may re-claim (idempotent heartbeat-style takeover)
    leases.claim_controller(
        new_client_run_binding_id(),
        task_id=task_id,
        run_id="run-1",
        client_session_id=tab_a.session_id,
        fence=fence_a,
        ttl=timedelta(minutes=5),
    )


def test_stale_fence_writes_zero_rows(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    sessions, leases, _, _ = stores
    session = _session()
    sessions.create_session(session)
    task_id = new_task_id()
    binding_id = new_client_run_binding_id()
    fence = ClientControlFence.issue()
    leases.claim_controller(
        binding_id,
        task_id=task_id,
        run_id="run-1",
        client_session_id=session.session_id,
        fence=fence,
        ttl=timedelta(minutes=5),
    )
    with pytest.raises(ClientFenceError):
        leases.renew(
            binding_id,
            task_id=task_id,
            run_id="run-1",
            fence=ClientControlFence.issue(),
            ttl=timedelta(minutes=5),
        )
    assert leases.renew(
        binding_id,
        task_id=task_id,
        run_id="run-1",
        fence=fence,
        ttl=timedelta(minutes=5),
    ).matches_fence(fence)


def test_expired_session_cannot_heartbeat(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    sessions, _, _, _ = stores
    expired = _session(status="expired")
    sessions.create_session(expired)
    with pytest.raises(ClientSessionExpiredError):
        sessions.heartbeat_session(
            expired.session_id, heartbeat_at=datetime.now(UTC)
        )


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
        published_at=datetime.now(UTC),
    )


def test_mount_narrows_and_binding_persists(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    sessions, _, _, _ = stores
    session = _session()
    sessions.create_session(session)
    profile = _profile()
    snapshot = MountedCapabilitySnapshot(
        client_session_id=session.session_id,
        frontend_app_id=profile.frontend_app_id,
        profile_revision=profile.revision,
        profile_digest=profile.profile_digest,
        mounted_readables=("app.ui.route",),
        mounted_actions=("app.ui.item.open",),
        ui_revision=2,
        mounted_at=datetime.now(UTC),
    )
    snapshot.ensure_subset_of(profile)
    sessions.save_mounted_snapshot(snapshot)
    loaded = sessions.get_mounted_snapshot(session.session_id)
    assert loaded is not None and loaded.snapshot_digest == snapshot.snapshot_digest
    narrowed = snapshot.model_copy(
        update={"mounted_actions": (), "ui_revision": 3}
    )
    sessions.save_mounted_snapshot(narrowed)
    reloaded = sessions.get_mounted_snapshot(session.session_id)
    assert reloaded is not None and reloaded.mounted_actions == ()

    binding = ClientRunBinding(
        binding_id=new_client_run_binding_id(),
        task_id=new_task_id(),
        run_id="run-1",
        client_session_id=session.session_id,
        profile_digest=profile.profile_digest,
        mounted_snapshot_digest=narrowed.snapshot_digest,
        task_capability_scope=("app.ui.item.open",),
        allowed_actions=(),
        binding_revision=1,
        created_at=datetime.now(UTC),
    )
    sessions.save_run_binding(binding)
    persisted = sessions.get_run_binding(
        binding.task_id, "run-1", binding.client_session_id
    )
    assert persisted is not None
    bumped = binding.narrow(mounted_actions=(), revision_reason="unmount")
    sessions.save_run_binding(bumped)
    again = sessions.get_run_binding(
        binding.task_id, "run-1", binding.client_session_id
    )
    assert again is not None and again.binding_revision == 2
