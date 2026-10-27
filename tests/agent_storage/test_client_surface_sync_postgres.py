"""Real transactions enforce current remount/binding facts across independent adapters."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from time import monotonic

import psycopg
import pytest
from agent_control_plane.client_admission import ClientAdmissionService, ClientBindingService
from agent_core.domain.client_capabilities import (
    MountedCapabilityNarrowingError,
    MountedCapabilitySnapshot,
)
from agent_core.domain.client_run_bindings import ClientBindingNarrowingError
from agent_core.domain.client_sessions import ClientSessionError, ClientSessionExpiredError
from agent_core.domain.identifiers import new_task_id
from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry
from psycopg.conninfo import make_conninfo

from tests.agent_storage.test_postgres_client_sessions import (
    _grant,
    _profile,
    _session,
)
from tests.agent_storage.test_postgres_client_sessions import (
    pytestmark as _postgres_mark,
)
from tests.agent_storage.test_postgres_client_sessions import (
    stores as _stores,
)

pytestmark = _postgres_mark
stores = _stores


def mounted(stores):
    sessions, leases, _, _ = stores
    profile = _profile()
    session = _session(grant=_grant(profile_digest=profile.profile_digest))
    sessions.create_session(session)
    snapshot = MountedCapabilitySnapshot(
        client_session_id=session.session_id,
        frontend_app_id=profile.frontend_app_id,
        profile_revision=profile.revision,
        profile_digest=profile.profile_digest,
        mounted_readables=("app.ui.route",),
        mounted_actions=("app.ui.item.open",),
        ui_revision=1,
        mounted_at=datetime.now(UTC),
    )
    ClientAdmissionService(sessions).mount(session.session_id, snapshot, profile=profile)
    binding = ClientBindingService(sessions, leases).bind_run(
        task_id=new_task_id(),
        run_id="run-1",
        session_id=session.session_id,
        task_capability_scope=snapshot.mounted_actions,
    )
    return session, snapshot, binding, profile


def test_same_names_remount_survives_replacement_adapter(stores):
    session, snapshot, first, profile = mounted(stores)
    _, leases, dsn, namespace = stores
    replacement = PostgresClientSessionRegistry(dsn, deployment_namespace=namespace)
    next_mount = snapshot.model_copy(update={"ui_revision": 2})
    ClientAdmissionService(replacement).mount(session.session_id, next_mount, profile=profile)
    second = ClientBindingService(replacement, leases).bind_run(
        task_id=first.binding.task_id,
        run_id="run-1",
        session_id=session.session_id,
        task_capability_scope=snapshot.mounted_actions,
    )
    assert second.binding.binding_id == first.binding.binding_id
    assert second.binding.binding_revision == 2
    assert second.binding.mounted_snapshot_digest == next_mount.snapshot_digest
    assert second.binding.binding_digest != first.binding.binding_digest
    assert not leases.get_active(first.binding.binding_id).matches_fence(first.controller_fence)
    assert leases.get_active(second.binding.binding_id).matches_fence(second.controller_fence)
    fresh = PostgresClientSessionRegistry(dsn, deployment_namespace=namespace)
    assert (
        fresh.get_run_binding(first.binding.task_id, "run-1", session.session_id) == second.binding
    )


def test_stale_binding_commit_rejected_and_original_history_preserved(stores):
    session, snapshot, first, _ = mounted(stores)
    sessions, _, dsn, namespace = stores
    replacement = PostgresClientSessionRegistry(dsn, deployment_namespace=namespace)
    replacement.save_mounted_snapshot(snapshot.model_copy(update={"ui_revision": 2}))
    stale = first.binding.narrow(mounted_actions=snapshot.mounted_actions, revision_reason="stale")
    with pytest.raises(ClientBindingNarrowingError, match="current mount"):
        sessions.save_run_binding(stale)
    assert (
        replacement.get_run_binding(first.binding.task_id, "run-1", session.session_id)
        == first.binding
    )
    assert replacement.get_mounted_snapshot(session.session_id).ui_revision == 2


def test_two_independent_narrowings_cannot_readd_each_others_capabilities(stores):
    session, snapshot, _, _ = mounted(stores)
    _, _, dsn, namespace = stores
    barrier = Barrier(2)

    def save(changes):
        adapter = PostgresClientSessionRegistry(dsn, deployment_namespace=namespace)
        candidate = snapshot.model_copy(update=changes)
        barrier.wait(timeout=5)
        try:
            adapter.save_mounted_snapshot(candidate)
            return candidate
        except MountedCapabilityNarrowingError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                save,
                [
                    {"ui_revision": 2, "mounted_actions": ()},
                    {"ui_revision": 3, "mounted_readables": ()},
                ],
            )
        )
    committed = [item for item in results if item is not None]
    assert len(committed) == 1
    reader = PostgresClientSessionRegistry(dsn, deployment_namespace=namespace)
    assert reader.get_mounted_snapshot(session.session_id) == committed[0]
    assert (
        reader.get_session(session.session_id).mounted_snapshot_digest
        == committed[0].snapshot_digest
    )


def test_closed_session_rejects_mount_and_binding_without_erasing_history(stores):
    session, snapshot, first, _ = mounted(stores)
    sessions, _, _, _ = stores
    sessions.close_session(session.session_id)
    with pytest.raises(ClientSessionExpiredError):
        sessions.save_mounted_snapshot(snapshot.model_copy(update={"ui_revision": 2}))
    with pytest.raises(ClientSessionExpiredError):
        sessions.save_run_binding(first.binding)
    assert (
        sessions.get_run_binding(first.binding.task_id, "run-1", session.session_id)
        == first.binding
    )
    assert sessions.get_mounted_snapshot(session.session_id) == snapshot


@pytest.mark.parametrize("shorter_timeout", [False, True])
def test_new_lock_wait_is_bounded_and_keeps_shorter_operator_limit(stores, shorter_timeout):
    session, snapshot, _, _ = mounted(stores)
    _, _, dsn, namespace = stores
    bounded_dsn = make_conninfo(dsn, options="-c lock_timeout=100ms") if shorter_timeout else dsn
    writer = PostgresClientSessionRegistry(bounded_dsn, deployment_namespace=namespace)
    with psycopg.connect(dsn) as blocker:
        blocker.execute(
            "SELECT client_session_id FROM client_sessions WHERE deployment_namespace=%s "
            "AND client_session_id=%s FOR UPDATE",
            (namespace, session.session_id),
        )
        started = monotonic()
        with pytest.raises(ClientSessionError, match="busy"):
            writer.save_mounted_snapshot(snapshot.model_copy(update={"ui_revision": 2}))
        elapsed = monotonic() - started
        assert elapsed < (0.8 if shorter_timeout else 2.0)
    assert writer.get_mounted_snapshot(session.session_id) == snapshot
