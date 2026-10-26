"""Real fenced PG source-condition, competing writers, one-use and scoped STOP proof."""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_storage import attach_segment_in_transaction, new_idempotency_record
from agent_storage.postgres.admission_atomic_surface import (
    AtomicSurfaceAborted,
    atomic_surface_transaction,
    observe_atomic_termination,
    start_atomic_surface,
)
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.message_surface_anchor import (
    CONSUMED,
    consume_message_anchor,
    lock_message_anchor,
)
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.task_event_positions import _lock_task
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tests.agent_storage.test_admission_atomic_surface import counts, effects, result, setup
from tests.agent_storage.test_postgres_agent_tasks import _append_handoff_events, _seed_session
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated
from tests.agent_storage.test_postgres_task_admission import _binding, _request

isolated_migration_dsn = _isolated
PROTOCOL = "atomic-message-surface/1"


def source(store):
    db = store._database
    q = _request()
    task = str(q.session.session_id)
    PostgresTaskAdmissionTransaction(db._dsn, deployment_namespace=db.deployment_namespace).admit(
        replace(q, binding=_binding(task))
    )
    events = PostgresEventStore(db._dsn, deployment_namespace=db.deployment_namespace)
    e = SessionEvent.create(
        session_id=q.session.session_id,
        sequence=q.events[-1].sequence + 1,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={
            "content": "source message",
            "origin": "human",
            "turn_id": str(uuid4()),
            "turn_index": 1,
        },
    )
    e = events.append(e)
    key = str(uuid4())
    c = {"event_id": str(e.event_id), "segment_id": task, "segment_sequence": e.sequence}
    store.save(
        new_idempotency_record(
            action=f"task-message:{task}",
            idempotency_key=key,
            request_hash="b" * 64,
            status_code=201,
            response_body={
                "task_id": task,
                "session_id": task,
                "appended": True,
                "sequence": e.sequence,
                "current_sequence": e.sequence,
                "content": "source message",
                "message_coordinates": c,
            },
        )
    )
    return (
        {"task": task, "run_id": str(uuid4()), "receipt_key": key, "request_hash": "b" * 64, **c},
        events,
        e,
    )


def successor(store, anchor):
    db = store._database
    root = SessionId(UUID(anchor["task"]))
    child = _seed_session(
        db._dsn, db.deployment_namespace, Path("/tmp") / ("owned-child-" + str(uuid4())), "Child"
    )
    _append_handoff_events(db._dsn, db.deployment_namespace, root=root, child=child)
    return child


def attach(store, c, anchor, child):
    attach_segment_in_transaction(
        c,
        store._database.deployment_namespace,
        task_id=TaskId(UUID(anchor["task"])),
        segment_id=child,
        predecessor_id=SessionId(UUID(anchor["task"])),
        reason=RolloverReason.RECOVERY,
    )


def consume(store, op, a):
    consume_message_anchor(
        store, task=a["task"], event_id=a["event_id"], scoped=op, digest="a" * 64, run=a["run_id"]
    )


def test_condition_and_consumption_commit_with_original_result(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    a, _, _ = source(store)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    before = store.get(action=f"task-message:{a['task']}", idempotency_key=a["receipt_key"])
    with atomic_surface_transaction(store, op, "a" * 64):
        assert lock_message_anchor(store, **a) is None
        effects(store)
        consume(store, op, a)
        result(store, op)
    assert counts(store) == [1, 1, 1]
    assert store.get(action=CONSUMED, idempotency_key=a["task"] + ":" + a["event_id"]) is not None
    assert store.get(action=f"task-message:{a['task']}", idempotency_key=a["receipt_key"]) == before
    _, other = setup(isolated_migration_dsn, PROTOCOL)
    assert start_atomic_surface(store, other, "a" * 64, protocol=PROTOCOL)
    with atomic_surface_transaction(store, other, "a" * 64):
        assert lock_message_anchor(store, **a) == "original_message_already_consumed"
    assert (
        observe_atomic_termination(store, op, "a" * 64, write=True, protocol=PROTOCOL)["state"]
        == "committed"
    )
    assert observe_atomic_termination(store, op, "a" * 64, write=False)["state"] == "unsupported"


@pytest.mark.parametrize(
    "fault", ["receipt", "hash", "event", "segment", "tail", "active", "namespace"]
)
def test_wrong_anchor_never_dispatches(fault, isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    a, events, e = source(store)
    if fault == "receipt":
        a["receipt_key"] = "not-observed"
    if fault == "hash":
        a["request_hash"] = "c" * 64
    if fault == "event":
        a["event_id"] = str(uuid4())
    if fault == "segment":
        a["segment_id"] = str(uuid4())
    if fault == "namespace":
        a["task"] = str(uuid4())
    if fault == "tail":
        events.append(
            SessionEvent.create(
                session_id=e.session_id,
                sequence=e.sequence + 1,
                event_type=EventType.MODEL_RESPONSE_RECEIVED,
                actor=EventActor.HARNESS,
                payload={"assistant_message": "later"},
            )
        )
    if fault == "active":
        child = successor(store, a)
        with store._database.connect() as c:
            attach(store, c, a, child)
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with atomic_surface_transaction(store, op, "a" * 64):
        assert lock_message_anchor(store, **a) is not None
    assert counts(store) == [0, 0, 0]
    assert store.get(action=CONSUMED, idempotency_key=a["task"] + ":" + a["event_id"]) is None


def test_external_append_waits_until_conditional_commit(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    a, events, e = source(store)
    started = Event()

    def append():
        started.set()
        return events.append(
            SessionEvent.create(
                session_id=e.session_id,
                sequence=e.sequence + 1,
                event_type=EventType.MODEL_RESPONSE_RECEIVED,
                actor=EventActor.HARNESS,
                payload={"assistant_message": "after"},
            )
        )

    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with ThreadPoolExecutor(1) as pool:
        with atomic_surface_transaction(store, op, "a" * 64):
            assert lock_message_anchor(store, **a) is None
            future = pool.submit(append)
            assert started.wait(5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            effects(store)
            consume(store, op, a)
            result(store, op)
        assert future.result(timeout=5).sequence == e.sequence + 1
    assert counts(store) == [1, 1, 1]


def test_task_pointer_lock_blocks_commit_then_rechecks(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    a, _, _ = source(store)
    child = successor(store, a)
    ready, release = Event(), Event()

    def change():
        with store._database.connect() as c:
            _lock_task(c, store._database.deployment_namespace, TaskId(UUID(a["task"])))
            attach(store, c, a, child)
            ready.set()
            assert release.wait(5)

    def condition():
        with atomic_surface_transaction(store, op, "a" * 64):
            return lock_message_anchor(store, **a)

    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)
    with ThreadPoolExecutor(2) as pool:
        writer = pool.submit(change)
        assert ready.wait(5)
        checking = pool.submit(condition)
        with pytest.raises(TimeoutError):
            checking.result(timeout=0.1)
        release.set()
        writer.result(timeout=5)
        assert checking.result(timeout=5) == "message_segment_not_active"
    assert counts(store) == [0, 0, 0]


def test_stop_rolls_back_surface_consumption_and_result(isolated_migration_dsn):
    store, op = setup(isolated_migration_dsn, PROTOCOL)
    a, _, _ = source(store)
    ready, release = Event(), Event()
    assert start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)

    def run():
        with pytest.raises(AtomicSurfaceAborted):
            with atomic_surface_transaction(store, op, "a" * 64):
                assert lock_message_anchor(store, **a) is None
                effects(store)
                consume(store, op, a)
                result(store, op)
                ready.set()
                assert release.wait(5)
                raise AtomicSurfaceAborted("owned rollback")

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(run)
        assert ready.wait(5)
        assert (
            observe_atomic_termination(store, op, "a" * 64, write=True, protocol=PROTOCOL)["state"]
            == "pending"
        )
        release.set()
        future.result(timeout=5)
    assert counts(store) == [0, 0, 0]
    assert store.get(action=CONSUMED, idempotency_key=a["task"] + ":" + a["event_id"]) is None
    assert (
        observe_atomic_termination(store, op, "a" * 64, write=False, protocol=PROTOCOL)["state"]
        == "terminated"
    )
    assert not start_atomic_surface(store, op, "a" * 64, protocol=PROTOCOL)


def test_rejected_condition_seals_original_without_dispatch(isolated_migration_dsn, monkeypatch):
    from zebra_agent_api import client_admission_operations as operations
    from zebra_agent_api.client_admission_atomic import execute_atomic_surface
    from zebra_agent_api.client_admission_message import OriginalMessage
    from zebra_agent_api.client_admission_termination import terminate_admission

    store, op = setup(isolated_migration_dsn, PROTOCOL)
    anchor, _, _ = source(store)
    ref = {k: v for k, v in anchor.items() if k not in {"task", "run_id"}}
    ref["request_hash"] = "c" * 64
    body = SimpleNamespace(
        kind="surface_mount",
        task=anchor["task"],
        run=anchor["run_id"],
        original_message=OriginalMessage(**ref),
    )
    app = SimpleNamespace(stores=SimpleNamespace(idempotency=store))
    request = SimpleNamespace(
        headers={"X-Zebra-Admission-Protocol": PROTOCOL},
        method="GET",
        path="/v1/admission-operations/" + op + "/message-surface-termination",
    )
    monkeypatch.setattr(operations, "_authorize", lambda *args: None)

    def forbidden(*args):
        pytest.fail("failed message condition dispatched a surface")

    monkeypatch.setattr(operations, "_dispatch", forbidden)
    key = b"k" * 32
    execute_atomic_surface(app, request, body, op, key, "a" * 64, op)
    saved = store.get(action="client-admission-v1-result", idempotency_key=op)
    assert saved is not None
    sealed = base64.b64decode(saved.response_body["sealed_response"])
    decoded = json.loads(AESGCM(key).decrypt(sealed[:12], sealed[12:], ("a" * 64).encode()))
    assert saved.response_body["response_status"] == 409
    assert decoded["reason"] == "original_message_receipt_unavailable"
    assert not decoded["non_commit_proven"] and counts(store) == [0, 0, 0]
    proof = terminate_admission(app, request, op, op, "a" * 64, {"kind": "surface_mount"})
    assert proof.body["contract_version"] == 6
    assert proof.body["state"] == "committed" and not proof.body["non_commit_proven"]
