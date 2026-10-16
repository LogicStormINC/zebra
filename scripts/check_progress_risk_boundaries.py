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


failures = []
for check in (
    priority,
    membership_read,
    evidence_retention,
    postcommit_dedup,
    unknown_write,
    pending_recovery_stage,
):
    try:
        check()
        print(check.__name__, "passed")
    except Exception as error:
        failures.append(check.__name__)
        print(check.__name__, type(error).__name__)
assert not failures, failures
