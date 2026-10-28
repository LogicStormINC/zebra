from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import PostgresLeaseStore, bootstrap_control_plane_epoch
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_approval import task_approval

from tests.agent_storage import test_postgres_command_wakeup_receipts as r
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _enable, _seed
from tests.agent_storage.test_postgres_command_wakeup_receipts import dsn, postgres_dsn

__all__ = ["dsn", "postgres_dsn"]


def seed(dsn):
    session = _seed(dsn)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    _enable(dsn)
    run_id = str(uuid4())
    command = SessionCommand(
        session_id=session.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=2,
        idempotency_key="original",
        payload={"run_id": run_id, "thread_id": str(session.session_id)},
    )
    event = SessionEvent.create(
        session_id=session.session_id,
        sequence=3,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key="original",
    )
    r._store(dsn).append(event)
    lease = r._handoff(dsn, event).lease
    r._refresh(dsn, session.session_id)
    r._start(dsn, event, lease)
    approval = r._event(
        dsn,
        session.session_id,
        EventType.APPROVAL_REQUESTED,
        {
            "tool_name": "command.run",
            "reason": "test approval",
            "policy_profile": "full_access",
            "arguments": {"command": ["python3", "-c", "print(1); print(2)"]},
            "tool_call_id": "call-original",
            "call_fingerprint": "a" * 64,
            "attempt_number": 1,
            "conversation": [],
            "model_calls_used": 1,
            "tool_calls_executed": 0,
            "assistant_message": "Waiting",
        },
    )
    r._commit(dsn, approval, lease)
    PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).release(
        session.session_id, fence=lease.fence
    )
    db = PostgresDatabase(dsn, deployment_namespace=NAMESPACE)
    return db, session.session_id, run_id


def body(view, decision="approve"):
    return {
        **{
            k: view[k]
            for k in (
                "approval_event_id",
                "expected_revision",
                "tool_call_id",
                "call_fingerprint",
                "run_id",
            )
        },
        "decision": decision,
        "operator": "test-user",
    }


@pytest.mark.parametrize("choice", ["approve", "reject"])
def test_exact_decision_atomic_idempotent_original_run(dsn, choice):
    db, tid, rid = seed(dsn)
    view = task_approval(db, tid, rid)
    assert view["arguments"]["command"][2] == "print(1); print(2)"
    intent = body(view, choice)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: task_approval(db, tid, rid, intent), range(2)))
    assert sorted(x["replayed"] for x in results) == [False, True]
    receipt = task_approval(db, tid, rid, receipt_event_id=view["approval_event_id"])
    assert receipt["decision"] == choice
    with pytest.raises(ValueError, match="approval_decision_conflict"):
        task_approval(db, tid, rid, body(view, "reject" if choice == "approve" else "approve"))
    events = r._store(dsn).list_for_session(tid)
    assert (
        sum(
            e.event_type in {EventType.APPROVAL_GRANTED, EventType.APPROVAL_REJECTED}
            for e in events
        )
        == 1
    )
    resumes = [
        e
        for e in events
        if e.event_type is EventType.SESSION_COMMAND_ACCEPTED and e.payload["kind"] == "resume"
    ]
    assert len(resumes) == (1 if choice == "approve" else 0)
    if resumes:
        assert "run_id" not in resumes[0].payload["payload"]
        from agent_storage.postgres.task_replay_headers import read_latest_run_header

        with db.connect_task_io() as c:
            header = read_latest_run_header(c, NAMESPACE, tid)
            assert header.run_id == rid and header.stop is None
    assert not any(e.event_type is EventType.MODEL_REQUEST_STARTED for e in events)


@pytest.mark.parametrize(
    "field",
    ["expected_revision", "call_fingerprint", "tool_call_id", "run_id", "approval_event_id"],
)
def test_stale_identity_never_writes(dsn, field):
    db, tid, rid = seed(dsn)
    view = task_approval(db, tid, rid)
    intent = body(view)
    intent[field] = 999 if field == "expected_revision" else str(uuid4())
    before = r._store(dsn).list_for_session(tid)
    with pytest.raises(ValueError):
        task_approval(db, tid, rid, intent)
    assert r._store(dsn).list_for_session(tid) == before


def test_resume_failure_rolls_back_decision_and_projections(dsn, monkeypatch):
    from agent_storage.postgres import task_approval as mod

    db, tid, rid = seed(dsn)
    view = task_approval(db, tid, rid)
    original = mod.append_event_in_transaction

    def fail(c, ns, event):
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED:
            raise RuntimeError("outbox unavailable")
        return original(c, ns, event)

    monkeypatch.setattr(mod, "append_event_in_transaction", fail)
    before = r._store(dsn).list_for_session(tid)
    with pytest.raises(RuntimeError):
        task_approval(db, tid, rid, body(view))
    assert r._store(dsn).list_for_session(tid) == before
    assert task_approval(db, tid, rid) == view


def test_internal_resume_handoff_and_cancel_boundary(dsn):
    from agent_storage.postgres.task_replay_headers import read_latest_run_header

    db, tid, rid = seed(dsn)
    view = task_approval(db, tid, rid)
    task_approval(db, tid, rid, body(view))
    resume = r._store(dsn).list_for_session(tid)[-1]
    claim = r._handoff(dsn, resume)
    assert claim.lease is not None
    # Native Worker accepts the exact queued continuation; no provider or tool invoked.
    with db.connect_task_io() as c:
        run = read_latest_run_header(c, NAMESPACE, tid)
        assert run.run_id == rid and run.stop is None
    r._refresh(dsn, tid)
    r._start(dsn, resume, claim.lease)
    second = r._event(
        dsn,
        tid,
        EventType.APPROVAL_REQUESTED,
        {
            **r._store(dsn).list_for_session(tid)[5].payload,
            "tool_name": "command.run",
            "reason": "second",
            "policy_profile": "full_access",
            "arguments": {"command": ["echo", "next"]},
            "tool_call_id": "next",
            "call_fingerprint": "b" * 64,
            "attempt_number": 2,
            "conversation": [],
            "model_calls_used": 1,
            "tool_calls_executed": 0,
        },
    )
    r._commit(dsn, second, claim.lease)
    new_view = task_approval(db, tid, rid)
    with pytest.raises(ValueError, match="approval_worker_busy"):
        task_approval(db, tid, rid, body(new_view))
    # Cancellation appended under the lease invalidates the previously rendered approval.
    cancel = r._event(dsn, tid, EventType.SESSION_CANCELLED, {"reason": "user cancelled"})
    r._commit(dsn, cancel, claim.lease)
    PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).release(tid, fence=claim.lease.fence)
    with pytest.raises(ValueError, match="approval_not_pending"):
        task_approval(db, tid, rid, body(new_view))
