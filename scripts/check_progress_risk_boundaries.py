"""Bounded advisory faults must not erase source events or pending evidence."""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.ports.worker_progress import WorkerProgressScope, WorkerProgressTimeout
from zebra_agent_worker.progress_recovery import WorkerProgressRecovery


def event(kind, **payload):
    return HarnessEventDraft(kind, EventActor.HARNESS, payload)


def priority():
    rows = []

    def append(draft):
        rows.append(draft)
        if draft.event_type is EventType.PUBLIC_OUTPUT:
            raise WorkerProgressTimeout("checkpoint", canonical_committed=True)

    sink = ProgressiveEventSink(
        append, user_input="check", policy=PublicOutputPolicy(wait_seconds=60)
    )
    sink._pending["receipt"] = None
    try:
        sink(event(EventType.MODEL_REQUEST_STARTED, attempt_number=1, model_call_id="main"))
        assert sum(r.event_type is EventType.MODEL_REQUEST_STARTED for r in rows) == 1
        assert sum(r.event_type is EventType.PUBLIC_OUTPUT for r in rows) == 1
    finally:
        sink.close()


def membership_read():
    def unavailable(*_args):
        raise TimeoutError("read unavailable")

    scope = WorkerProgressScope("local", uuid4(), "run", uuid4(), 1)
    tasks = SimpleNamespace(
        worker_output_published=unavailable, worker_receipts_covered=unavailable
    )
    recovery = WorkerProgressRecovery(tasks, SimpleNamespace(scope=scope), lambda: None, 8)
    for read in (
        lambda: recovery.output_published("output"),
        lambda: recovery.receipts_covered(("receipt",)),
    ):
        try:
            read()
        except WorkerProgressTimeout as error:
            assert error.stage == "observation" and not error.canonical_committed
        else:
            raise AssertionError("read timeout lost its stage")
    rows = []
    sink = ProgressiveEventSink(
        rows.append,
        user_input="check",
        policy=PublicOutputPolicy(wait_seconds=60),
        output_published=recovery.output_published,
    )
    sink._active.add("model:pending")
    sink._wait_elapsed(sink._timer_generation)
    assert sink._timer_error is None, "advisory read poisoned the execution"
    sink(event(EventType.MODEL_REQUEST_STARTED, attempt_number=1, model_call_id="next"))
    sink.close()
    assert len(rows) == 1 and rows[0].event_type is EventType.MODEL_REQUEST_STARTED


def evidence_retention():
    def unavailable(_output):
        raise WorkerProgressTimeout("observation", canonical_committed=False)

    rows = []
    sink = ProgressiveEventSink(
        rows.append, user_input="check", policy=PublicOutputPolicy(), output_published=unavailable
    )
    sink._pending["receipt"] = None
    try:
        sink._publish_pending()
    except WorkerProgressTimeout:
        pass
    assert "receipt" in sink._pending, "failed read discarded evidence before publication"
    assert not rows
    sink._output_published = lambda _output: False
    sink._publish_pending()
    sink._publish_pending()
    assert len(rows) == 1 and not sink._pending
    sink.close()


def postcommit_dedup():
    rows = []

    def append(draft):
        rows.append(draft)
        raise WorkerProgressTimeout("checkpoint", canonical_committed=True)

    sink = ProgressiveEventSink(append, user_input="check", policy=PublicOutputPolicy())
    sink._pending["receipt"] = None
    try:
        sink._publish_pending()
    except WorkerProgressTimeout:
        pass
    sink._publish_pending()
    assert len(rows) == 1 and not sink._pending and sink._published_count == 1
    sink.close()


def unknown_write():
    attempts = []

    def append(draft):
        attempts.append(draft)
        raise WorkerProgressTimeout("canonical_append", canonical_committed=False)

    sink = ProgressiveEventSink(append, user_input="check", policy=PublicOutputPolicy())
    try:
        sink(event(EventType.MODEL_REQUEST_STARTED, attempt_number=1, model_call_id="unknown"))
    except WorkerProgressTimeout as error:
        assert not error.canonical_committed
    else:
        raise AssertionError("unknown canonical write was accepted")
    assert len(attempts) == 1
    sink.close()


def pending_recovery_stage():
    recovery = WorkerProgressRecovery(
        None, SimpleNamespace(state=SimpleNamespace(pending_commentary=object())), lambda: None, 8
    )
    with patch(
        "zebra_agent_worker.progress_recovery.repair_commentary",
        side_effect=TimeoutError("recovery unavailable"),
    ):
        try:
            recovery.persist_with(lambda _draft: None)
        except WorkerProgressTimeout as error:
            assert error.stage == "prepare" and not error.canonical_committed
        else:
            raise AssertionError("required recovery failure was ignored")


def _check_verified_source(warm: bool):
    from dataclasses import replace

    from agent_core.domain.events import SessionEvent
    from agent_core.harness.commentary_progress import reserve_commentary
    from agent_core.harness.model_commentary import plan_response
    from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage
    from agent_core.ports.worker_progress import WorkerProgressHead, WorkerProgressState
    from zebra_agent_worker.commentary_recovery import repair_commentary

    identity = uuid4()
    scope = WorkerProgressScope("local", identity, "reuse", uuid4(), 1)
    payload = plan_response(
        {
            "attempt_number": 1,
            "model_call_id": "reuse",
            "assistant_message": "已确认的公开进度",
            "response_stage": "tool_loop",
        },
        0,
    )
    source = SessionEvent.create(
        session_id=identity,
        sequence=2,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload=payload,
    )
    entry = TaskEvent(identity, 2, identity, 2, source)
    page = TaskEventPage((entry,), 1, 2, len(source.model_dump_json().encode()))
    values = WorkerProgressState().model_dump()
    reserve_commentary(payload, 2, values)
    head = WorkerProgressHead(scope, 2, source.event_id, WorkerProgressState(**values))
    reads = []
    outputs = []
    checks = []

    def point(*_args, **kwargs):
        reads.append(kwargs)
        assert kwargs["limit"] == 1
        return page

    recovery = SimpleNamespace(
        head=head,
        tasks=SimpleNamespace(read_event_page=point),
        ownership_check=lambda: checks.append(1),
    )
    calls = 0

    def catch_up():
        nonlocal calls
        calls += 1
        if calls == 1:
            return entry if warm else None
        recovery.head = replace(
            head,
            state=head.state.model_copy(
                update={"pending_commentary": None, "commentary_published_count": 1}
            ),
        )
        return None

    recovery.catch_up = catch_up
    repair_commentary(recovery, outputs.append)
    assert len(outputs) == 1 and recovery.head.state.pending_commentary is None
    assert len(checks) >= 2
    assert len(reads) == int(not warm), "verified source was redundantly read"
    if warm:
        from agent_core.ports.task_projection_checkpoints import CheckpointConflict

        recovery.head = head
        recovery.catch_up = lambda: replace(entry, task_id=uuid4())
        try:
            repair_commentary(recovery, outputs.append)
        except CheckpointConflict:
            pass
        else:
            raise AssertionError("foreign verified-source identity accepted")


def verified_source_reuse():
    _check_verified_source(True)
    _check_verified_source(False)


def progress_head_read():
    import sqlite3

    from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
    from agent_core.ports.worker_progress import MAX_PROGRESS_STATE_BYTES, WorkerProgressState
    from agent_storage.worker_progress import WorkerProgressStoreMixin, progress_schema

    scope = WorkerProgressScope("local", uuid4(), "bounded-head", uuid4(), 1)
    store = WorkerProgressStoreMixin()
    statements = []

    def guarded_row(cursor, values):
        row = dict(zip((column[0] for column in cursor.description), values, strict=True))
        if row.get("state_json") is not None:
            size = len(row["state_json"].encode())
            assert size <= MAX_PROGRESS_STATE_BYTES and size == row.get("state_bytes", size), (
                "invalid checkpoint body crossed the database hydration boundary"
            )
        return row

    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = guarded_row
        connection.execute(progress_schema()[0])
        connection.set_trace_callback(statements.append)
        for initial in (False, True):
            statements.clear()
            try:
                head = store._progress_head(connection, scope, initial=initial)
            except CheckpointNotReady:
                assert not initial
            else:
                assert initial and head.through_sequence == 0
            assert len(statements) == 1
        connection.execute("PRAGMA ignore_check_constraints=ON")
        state = WorkerProgressState(policy_json="公开进度 🐎")
        text = state.model_dump_json()
        padded = text + " " * (MAX_PROGRESS_STATE_BYTES - len(text.encode()))
        for body, size, valid in (
            (text, len(text.encode()), True),
            (padded, MAX_PROGRESS_STATE_BYTES, True),
            (text, len(text), False),
            (padded + "x", MAX_PROGRESS_STATE_BYTES, False),
            (text, 0, False),
            (padded + "x", MAX_PROGRESS_STATE_BYTES + 1, False),
        ):
            connection.execute("DELETE FROM worker_progress_heads")
            connection.execute(
                "INSERT INTO worker_progress_heads VALUES (?,?,?,?,?,?,?,?,?,?)",
                (scope.namespace, str(scope.task_id), str(scope.anchor_event_id), scope.version,
                 scope.run_id, scope.anchor_sequence, 1, str(scope.anchor_event_id), body, size),
            )
            statements.clear()
            try:
                head = store._progress_head(connection, scope)
            except CheckpointConflict:
                assert not valid
            else:
                assert valid and head.state == state and head.through_sequence == 1
            assert len(statements) == 1, "checkpoint metadata/body required two SQL statements"


def signature_membership_batch():
    import sqlite3
    from contextlib import contextmanager

    from agent_core.domain.events import SessionEvent
    from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage
    from agent_core.ports.task_projection_checkpoints import CheckpointConflict
    from agent_storage.worker_progress import WorkerProgressStoreMixin, progress_schema

    scope = WorkerProgressScope("local", uuid4(), "batch", uuid4(), 1)
    store = WorkerProgressStoreMixin()
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        for sql in progress_schema():
            connection.execute(sql)

        @contextmanager
        def transaction(*, write=False):
            with connection:
                yield connection

        # This check isolates real index/fold SQL; native suites retain source/Run checks.
        store._progress_connection = transaction
        store._progress_run = lambda *_args: SimpleNamespace(stop=None)
        store._progress_canonical = lambda _connection, _scope, page: page
        statements = []
        connection.set_trace_callback(statements.append)

        def page(after, outputs):
            entries = []
            for position, (key, content) in enumerate(outputs, after + 1):
                source = SessionEvent.create(
                    session_id=scope.task_id, sequence=position,
                    event_type=EventType.PUBLIC_OUTPUT, actor=EventActor.HARNESS,
                    payload={"attempt_number": 1, "output_id": key, "kind": "status",
                             "phase": "started", "origin": "system", "content": content},
                )
                entries.append(TaskEvent(scope.task_id, position, scope.task_id, position, source))
            return TaskEventPage(tuple(entries), after, after + len(entries), 4096)

        def reads():
            return sum(sql.startswith("SELECT") and "FROM worker_progress_outputs" in sql
                       for sql in statements)

        first = page(0, [(str(i), "same") for i in range(8)] + [("0", "same")])
        head = store.advance_worker_progress(scope, first)
        assert head.state.published_count == 8
        assert reads() == 1, "signature membership still performs per-output SQL"
        statements.clear()
        second = page(head.through_sequence, [("0", "same"), ("8", "same")])
        head = store.advance_worker_progress(scope, second)
        assert head.state.published_count == 9 and reads() == 1
        for outputs in ([("0", "changed")], [("new", "first"), ("new", "changed")]):
            try:
                store.advance_worker_progress(scope, page(head.through_sequence, outputs))
            except CheckpointConflict:
                pass
            else:
                raise AssertionError("conflicting output signature accepted")
            assert store._progress_head(connection, scope) == head
            count = connection.execute("SELECT count(*) FROM worker_progress_outputs").fetchone()[0]
            assert count == 9


failures = []
for check in (
    priority,
    membership_read,
    evidence_retention,
    postcommit_dedup,
    unknown_write,
    pending_recovery_stage,
    verified_source_reuse,
    progress_head_read,
    signature_membership_batch,
):
    try:
        check()
        print(check.__name__, "passed")
    except Exception as error:
        failures.append(check.__name__)
        print(check.__name__, type(error).__name__)
assert not failures, failures
