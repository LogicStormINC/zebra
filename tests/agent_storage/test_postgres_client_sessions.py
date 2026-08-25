"""Real-PostgreSQL acceptance for client sessions and control leases (v32)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.client_capabilities import (
    ClientActionContract,
    ClientActionRisk,
    ClientReadableContract,
    FrontendCapabilityProfileVersion,
    MountedCapabilityNarrowingError,
    MountedCapabilitySnapshot,
)
from agent_core.domain.client_run_bindings import ClientBindingNarrowingError, ClientRunBinding
from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLeaseError,
    ClientFenceError,
    ClientSession,
    ClientSessionExpiredError,
    ClientSessionGrant,
)
from agent_core.domain.identifiers import (
    SessionId,
    TaskId,
    new_client_run_binding_id,
    new_session_id,
    new_task_id,
)
from agent_storage.postgres.client_sessions import (
    PostgresClientControlLeaseStore,
    PostgresClientSessionRegistry,
)
from agent_storage.postgres.migration_runner import apply_postgres_migrations
from agent_storage.postgres.migrations import MIGRATIONS
from psycopg import sql
from psycopg.conninfo import make_conninfo

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
        "credential_hash": "d" * 64,
        "created_at": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + timedelta(hours=2),
    }
    payload.update(overrides)
    return ClientSession.model_validate(payload)


def _save_binding(
    sessions: PostgresClientSessionRegistry,
    session: ClientSession,
    *,
    task_id: TaskId | None = None,
    run_id: str = "run-1",
) -> ClientRunBinding:
    binding = ClientRunBinding(
        binding_id=new_client_run_binding_id(),
        task_id=task_id or new_task_id(),
        run_id=run_id,
        client_session_id=session.session_id,
        profile_digest=session.grant.profile_digest,
        mounted_snapshot_digest="b" * 64,
        task_capability_scope=("app.ui.item.open",),
        allowed_actions=("app.ui.item.open",),
        binding_revision=1,
        created_at=datetime.now(UTC),
    )
    sessions.save_run_binding(binding)
    return binding


def test_two_tabs_claim_and_only_one_wins(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    sessions, leases, _, _ = stores
    tab_a = _session()
    tab_b = _session()
    sessions.create_session(tab_a)
    sessions.create_session(tab_b)
    task_id = new_task_id()
    binding_a = _save_binding(sessions, tab_a, task_id=task_id)
    binding_b = _save_binding(sessions, tab_b, task_id=task_id)
    fence_a = ClientControlFence.issue()
    fence_b = ClientControlFence.issue()
    lease = leases.claim_controller(
        binding_a.binding_id,
        task_id=task_id,
        run_id="run-1",
        client_session_id=tab_a.session_id,
        fence=fence_a,
        ttl=timedelta(minutes=5),
    )
    assert lease.matches_fence(fence_a)
    with pytest.raises(ClientControlLeaseError):
        leases.claim_controller(
            binding_b.binding_id,
            task_id=task_id,
            run_id="run-1",
            client_session_id=tab_b.session_id,
            fence=fence_b,
            ttl=timedelta(minutes=5),
        )
    with pytest.raises(ClientControlLeaseError):
        leases.claim_controller(
            new_client_run_binding_id(),
            task_id=task_id,
            run_id="run-1",
            client_session_id=tab_a.session_id,
            fence=fence_a,
            ttl=timedelta(minutes=5),
        )
    # the incumbent may re-claim (idempotent heartbeat-style takeover)
    leases.claim_controller(
        binding_a.binding_id,
        task_id=task_id,
        run_id="run-1",
        client_session_id=tab_a.session_id,
        fence=fence_a,
        ttl=timedelta(minutes=5),
    )


def test_stale_fence_writes_zero_rows(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    sessions, leases, dsn, namespace = stores
    session = _session()
    sessions.create_session(session)
    task_id = new_task_id()
    binding = _save_binding(sessions, session, task_id=task_id)
    binding_id = binding.binding_id
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
    with pytest.raises(ClientFenceError):
        leases.renew(
            new_client_run_binding_id(),
            task_id=task_id,
            run_id="run-1",
            fence=fence,
            ttl=timedelta(minutes=5),
        )
    assert leases.renew(
        binding_id,
        task_id=task_id,
        run_id="run-1",
        fence=fence,
        ttl=timedelta(minutes=5),
    ).matches_fence(fence)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            UPDATE client_control_leases SET expires_at = %s
            WHERE deployment_namespace = %s AND run_binding_id = %s
            """,
            (datetime.now(UTC) - timedelta(seconds=1), namespace, binding_id),
        )
    with pytest.raises(ClientFenceError):
        leases.renew(
            binding_id,
            task_id=task_id,
            run_id="run-1",
            fence=fence,
            ttl=timedelta(minutes=5),
        )
    assert leases.get_active(binding_id) is None


def test_expired_session_cannot_heartbeat(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    sessions, _, _, _ = stores
    expired = _session(status="expired")
    sessions.create_session(expired)
    with pytest.raises(ClientSessionExpiredError):
        sessions.heartbeat_session(expired.session_id, heartbeat_at=datetime.now(UTC))
    now = datetime.now(UTC)
    elapsed = _session(
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    sessions.create_session(elapsed)
    with pytest.raises(ClientSessionExpiredError):
        sessions.heartbeat_session(elapsed.session_id, heartbeat_at=now)
    stored = sessions.get_session(elapsed.session_id)
    assert stored is not None and stored.status.value == "expired"


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
    narrowed = snapshot.model_copy(update={"mounted_actions": (), "ui_revision": 3})
    sessions.save_mounted_snapshot(narrowed)
    reloaded = sessions.get_mounted_snapshot(session.session_id)
    assert reloaded is not None and reloaded.mounted_actions == ()
    with pytest.raises(MountedCapabilityNarrowingError):
        sessions.save_mounted_snapshot(narrowed.model_copy(update={"ui_revision": 2}))

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
    persisted = sessions.get_run_binding(binding.task_id, "run-1", binding.client_session_id)
    assert persisted is not None
    bumped = binding.narrow(mounted_actions=(), revision_reason="unmount")
    sessions.save_run_binding(bumped)
    again = sessions.get_run_binding(binding.task_id, "run-1", binding.client_session_id)
    assert again is not None and again.binding_revision == 2
    with pytest.raises(ClientBindingNarrowingError):
        sessions.save_run_binding(again.model_copy(update={"mounted_snapshot_digest": "c" * 64}))
    with pytest.raises(ClientBindingNarrowingError):
        sessions.save_run_binding(again.model_copy(update={"binding_revision": 4}))


def test_active_binding_is_resolved_from_the_execution_segment(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    sessions, leases, dsn, namespace = stores
    session = _session()
    sessions.create_session(session)
    task_id = new_task_id()
    segment_id = new_session_id()
    binding = ClientRunBinding(
        binding_id=new_client_run_binding_id(),
        task_id=task_id,
        run_id="run-segment",
        client_session_id=session.session_id,
        profile_digest="a" * 64,
        mounted_snapshot_digest="b" * 64,
        task_capability_scope=("app.ui.item.open",),
        allowed_actions=("app.ui.item.open",),
        binding_revision=1,
        created_at=datetime.now(UTC),
    )
    sessions.save_run_binding(binding)
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as connection:
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        connection.execute(
            """
            INSERT INTO session_projections (
                deployment_namespace, session_id, title, status, created_at,
                updated_at, current_sequence
            ) VALUES (%s, %s, 'client segment', 'running', %s, %s, 0)
            """,
            (namespace, segment_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO agent_tasks (
                deployment_namespace, task_id, root_session_id,
                active_segment_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (namespace, task_id, segment_id, segment_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO execution_segments (
                deployment_namespace, session_id, task_id, predecessor_id,
                segment_index, visibility, rollover_reason
            ) VALUES (%s, %s, %s, NULL, 0, 'internal', NULL)
            """,
            (namespace, segment_id, task_id),
        )
    fence = ClientControlFence.issue()
    leases.claim_controller(
        binding.binding_id,
        task_id=task_id,
        run_id=binding.run_id,
        client_session_id=session.session_id,
        fence=fence,
        ttl=timedelta(minutes=5),
    )

    assert sessions.get_active_run_binding(segment_id) == binding
    assert sessions.get_active_run_binding(SessionId(task_id)) is None


def test_v34_upgrades_legacy_client_rows_without_losing_terminal_results(
    stores: tuple[PostgresClientSessionRegistry, PostgresClientControlLeaseStore, str, str],
) -> None:
    _, _, dsn, _ = stores
    schema = f"client_security_upgrade_{uuid4().hex}"
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(dsn, options=f"-c search_path={schema}")
    namespace = "upgrade-test"
    older_binding_id, newest_binding_id = uuid4(), uuid4()
    pending_effect_id, succeeded_effect_id = uuid4(), uuid4()
    pending_task_id, succeeded_task_id = uuid4(), uuid4()
    try:
        with psycopg.connect(isolated) as connection:
            connection.execute(
                """
                CREATE TABLE zebra_schema_migrations (
                    version BIGINT PRIMARY KEY, name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            for migration in (item for item in MIGRATIONS if item.version < 34):
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO zebra_schema_migrations (version, name, checksum)
                    VALUES (%s, %s, %s)
                    """,
                    (migration.version, migration.name, migration.checksum),
                )
            for binding_id, revision, bound_at in (
                (older_binding_id, 1, datetime(2026, 1, 1, tzinfo=UTC)),
                (newest_binding_id, 2, datetime(2026, 1, 2, tzinfo=UTC)),
            ):
                connection.execute(
                    """
                    INSERT INTO frontend_capability_bindings (
                        deployment_namespace, binding_id, host_app_id,
                        namespace_id, frontend_app_id, revision,
                        profile_digest, binding_revision, bound_at
                    ) VALUES (%s, %s, 'host', 'tenant', 'web', %s, %s, %s, %s)
                    """,
                    (namespace, binding_id, revision, "a" * 64, revision, bound_at),
                )
            connection.execute(
                """
                INSERT INTO client_sessions (
                    deployment_namespace, client_session_id, host_app_id,
                    namespace_id, frontend_app_id, origin, user_ref,
                    profile_digest, grant_json, created_at, expires_at
                ) VALUES (%s, %s, 'host', 'tenant', 'web',
                          'https://example.test', 'user', %s, '{}', %s, %s)
                """,
                (namespace, uuid4(), "a" * 64, datetime.now(UTC), datetime.now(UTC)),
            )
            connection.execute(
                """
                INSERT INTO client_control_leases (
                    deployment_namespace, task_id, run_id, run_binding_id,
                    client_session_id, fence_hash, expires_at
                ) VALUES (%s, %s, 'orphan-run', NULL, %s, %s, %s)
                """,
                (
                    namespace,
                    uuid4(),
                    uuid4(),
                    "f" * 64,
                    datetime.now(UTC) + timedelta(minutes=5),
                ),
            )
            for effect_id, task_id, status in (
                (pending_effect_id, pending_task_id, "pending"),
                (succeeded_effect_id, succeeded_task_id, "succeeded"),
            ):
                connection.execute(
                    """
                    INSERT INTO client_effects (
                        deployment_namespace, effect_id, task_id, run_id,
                        client_session_id, tool_call_id, action_name,
                        arguments_json, action_contract_digest,
                        client_binding_digest, fence_hash,
                        expected_ui_revision, idempotency_key, request_digest,
                        status, requested_at, expires_at
                    ) VALUES (%s, %s, %s, 'run', %s, %s, 'app.open', '{}',
                              %s, %s, %s, 0, %s, %s, %s, %s, %s)
                    """,
                    (
                        namespace,
                        effect_id,
                        task_id,
                        uuid4(),
                        uuid4(),
                        "b" * 64,
                        "c" * 64,
                        "d" * 64,
                        str(effect_id),
                        "e" * 64,
                        status,
                        datetime.now(UTC),
                        datetime.now(UTC),
                    ),
                )

        apply_postgres_migrations(isolated)

        with psycopg.connect(isolated) as connection:
            assert connection.execute(
                "SELECT binding_id FROM frontend_capability_bindings"
            ).fetchall() == [(newest_binding_id,)]
            assert (
                connection.execute("SELECT count(*) FROM client_control_leases").fetchone()[0] == 0
            )
            assert (
                connection.execute(
                    """
                SELECT is_nullable FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'client_control_leases'
                  AND column_name = 'run_binding_id'
                """,
                    (schema,),
                ).fetchone()[0]
                == "NO"
            )
            assert connection.execute(
                "SELECT status, credential_hash FROM client_sessions"
            ).fetchone() == ("closed", "0" * 64)
            rows = connection.execute(
                """
                SELECT effect_id, parent_session_id, status
                FROM client_effects ORDER BY effect_id
                """
            ).fetchall()
            by_effect = {effect_id: (parent, status) for effect_id, parent, status in rows}
            assert by_effect[pending_effect_id] == (pending_task_id, "cancelled")
            assert by_effect[succeeded_effect_id] == (succeeded_task_id, "succeeded")
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
