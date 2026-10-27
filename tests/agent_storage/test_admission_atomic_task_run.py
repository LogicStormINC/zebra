"""Task + first RUN + native wakeups are visible only after the original commit."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from agent_storage.postgres.admission_atomic_surface import (
    AtomicSurfaceAborted,
    atomic_surface_transaction,
    observe_atomic_termination,
    start_atomic_surface,
)
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.session_queue import create_queued_session

from tests.agent_storage.test_admission_atomic_surface import result, setup
from tests.agent_storage.test_admission_atomic_task import counts
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated

isolated_migration_dsn = _isolated
PROTOCOL = "atomic-task-run/1"


def effects(store):
    from uuid import uuid4

    from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant

    from tests.agent_storage.test_command_wakeup import _binding

    context = _binding(str(uuid4())).host_capability.host_context
    verified = VerifiedHostGrant(
        context, context.grant_id, JwtAlgorithm.RS256, context.origin, "user-a"
    )
    db = store._database
    parsed = parse_create_session_payload(
        {"title": "queued", "prompt": "hello", "workspace": "/tmp/atomic-run", "execute": True}
    )
    response = create_queued_session(
        SimpleNamespace(artifact_payloads=object()),
        parsed,
        admission_dsn=db._dsn,
        admission_namespace=db.deployment_namespace,
        initial_run_id="run:exact-owned",
        host_context=context,
        verified_host_grant=verified,
    )
    assert response.status_code == 201 and response.body["status"] == "queued"
    return response


def command_counts(store):
    with store._database.connect() as c:
        return [
            c.execute(
                f"SELECT count(*) AS n FROM {table} WHERE deployment_namespace=%s",
                (store._database.deployment_namespace,),
            ).fetchone()["n"]
            for table in ("session_command_pending", "broker_outbox")
        ]


def enable(store):
    with store._database.connect() as c:
        c.execute(
            "INSERT INTO command_wakeup_rollouts(deployment_namespace,admission_enabled) "
            "VALUES(%s,true)",
            (store._database.deployment_namespace,),
        )


def observe(store, op, write):
    return observe_atomic_termination(store, op, "a" * 64, write=write, protocol=PROTOCOL)


def test_uncommitted_run_not_discoverable_stop_rolls_back_everything(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    enable(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    ready, release = Event(), Event()

    def run():
        with pytest.raises(AtomicSurfaceAborted):
            with atomic_surface_transaction(store, op, "a" * 64):
                effects(store)
                assert command_counts(store) == [1, 1]
                result(store, op)
                ready.set()
                assert release.wait(5)

    with ThreadPoolExecutor(1) as pool:
        task = pool.submit(run)
        assert ready.wait(5)
        assert counts(store) == [0] * 5 and command_counts(store) == [0, 0]
        assert observe(store, op, True)["state"] == "pending"
        release.set()
        task.result()
    assert counts(store) == [0] * 5 and command_counts(store) == [0, 0]
    assert observe(store, op, False)["state"] == "terminated"
    assert not start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)


def test_committed_run_has_exact_persisted_identity_never_noncommit(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    enable(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with atomic_surface_transaction(store, op, "a" * 64):
        effects(store)
        result(store, op)
    assert command_counts(store) == [1, 1]
    with store._database.connect() as c:
        event = c.execute(
            "SELECT payload FROM session_events WHERE deployment_namespace=%s "
            "AND event_type='session_command_accepted'",
            (store._database.deployment_namespace,),
        ).fetchone()
        assert event["payload"]["payload"]["run_id"] == "run:exact-owned"
    assert observe(store, op, True)["state"] == "committed"
    assert (
        observe_atomic_termination(store, op, "a" * 64, write=True, protocol="atomic-task/1")[
            "state"
        ]
        == "unsupported"
    )
