import json
import socket
from datetime import UTC, datetime
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_expression import PublicExpression
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from zebra_agent_config import load_settings

from tests.agent_core.test_public_output import draft, verified_facts
from tests.agent_storage.test_postgres_scalar_task_replay_headers import scratch as _scratch_fixture

scratch = _scratch_fixture


def completion(content: str) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=datetime.now(UTC),
        ),
        call_metadata=ModelCallMetadata(usage=ModelUsage(input_tokens=20, output_tokens=12)),
    )


def expression(complete, events, *, calls_used=0, max_calls=1):
    return PublicExpression(
        complete,
        events.append,
        max_calls=max_calls,
        deadline_s=1,
        max_input_characters=1600,
        max_output_tokens=128,
        calls_used=calls_used,
    )


def test_expression_preserves_every_fact_and_accounts_separately() -> None:
    events: list[HarnessEventDraft] = []

    def complete(messages, policy, deadline):
        assert json.loads(messages[-1].content) == ["Read 2 of 20 records.", "No write receipt."]
        assert policy.thinking_mode.value == "disabled"
        assert policy.tool_choice.value == "none" and policy.max_output_tokens == 128
        assert policy.reasoning_effort is None and deadline == 1
        return completion('{"order":[1,0],"lead":"findings"}')

    formatter = expression(complete, events)
    value = formatter.express(["Read 2 of 20 records.", "No write receipt."], chinese=False)
    assert (
        value is not None
        and value[0] == "Confirmed findings:\n\nNo write receipt.\n\nRead 2 of 20 records."
    )
    assert events[0].payload["purpose"] == "public_expression"
    assert events[1].payload["response_stage"] == "public_expression"
    assert events[1].payload["input_tokens"] == 20
    assert events[1].payload["model_call_id"] == value[1]
    assert formatter.express(["Read 2 of 20 records."], chinese=False) is None


@pytest.mark.parametrize(
    "content",
    [
        '{"order":[0],"lead":"findings"}',
        '{"order":[0,0],"lead":"none"}',
        '{"order":[false,1],"lead":"none"}',
        '{"order":[0,1],"lead":[]}',
        '{"order":[0,1],"lead":"Succeeded in writing"}',
        "Not JSON",
    ],
)
def test_invalid_expression_cannot_change_fact_fallback(content: str) -> None:
    events: list[HarnessEventDraft] = []
    assert (
        expression(lambda *_: completion(content), events).express(
            ["Read 2 of 20 records.", "No write receipt."], chinese=False
        )
        is None
    )
    assert events[-1].payload["response_stage"] == "public_expression"


def test_failure_or_recovered_budget_never_retries_expression() -> None:
    events: list[HarnessEventDraft] = []

    def unavailable(*_):
        raise TimeoutError("provider unavailable")

    formatter = expression(unavailable, events)
    assert formatter.express(["Sample only."], chinese=False) is None
    assert formatter.express(["Sample only."], chinese=False) is None
    assert len(events) == 1 and events[0].event_type is EventType.MODEL_REQUEST_STARTED
    assert expression(unavailable, events, calls_used=1).express(["sample"], chinese=False) is None
    assert len(events) == 1


def test_oversized_fact_is_not_truncated_or_sent_to_model() -> None:
    events: list[HarnessEventDraft] = []
    assert (
        expression(lambda *_: pytest.fail("must not call model"), events).express(
            ["x" * 1600 + " Only a partial page."], chinese=False
        )
        is None
    )
    assert events == []


def test_public_output_defaults_are_central_and_reject_unbounded_budgets() -> None:
    settings = load_settings({"ZEBRA_PUBLIC_OUTPUT_EXPRESSION_MAX_CALLS": "1"})
    assert settings.public_output.expression_max_calls == 1
    assert PublicOutputPolicy().expression_max_calls == 0
    for values in (
        {"expression_max_calls": 3},
        {"delta_seconds": 1},
        {"expression_deadline_seconds": 10},
        {"expression_output_tokens": 129},
        {"expression_output_tokens": 256},
        {"max_outputs": 1.5},
        {"max_outputs": True},
        {"wait_seconds": "slow"},
        {"version": "x" * 65},
    ):
        with pytest.raises(ValueError):
            PublicOutputPolicy(**values)


def test_confirmed_batch_is_published_while_another_operation_is_still_running() -> None:
    events: list[HarnessEventDraft] = []
    published = Event()

    def append(event):
        events.append(event)
        if (
            event.event_type is EventType.PUBLIC_OUTPUT
            and "third" in event.payload["evidence_refs"]
        ):
            published.set()

    sink = ProgressiveEventSink(append, user_input="Compare pages", policy=PublicOutputPolicy())
    try:
        sink.operation_started("slow-operation")
        for call_id in ("first", "second", "third"):
            sink(
                draft(
                    EventType.TOOL_EXECUTION_COMPLETED,
                    tool_call_id=call_id,
                    status="executed",
                    metadata={
                        "public_facts": verified_facts(f"Page {call_id} only; not full coverage.")
                    },
                )
            )
            if call_id == "first":
                assert events[-1].event_type is EventType.PUBLIC_OUTPUT
                assert events[-1].payload["evidence_refs"] == ["first"]
        assert published.wait(1), "confirmed milestones must not wait for the next model request"
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert len(outputs) == 2 and outputs[-1]["evidence_refs"] == ["second", "third"]
        assert outputs[-1]["content"] == (
            "Page second only; not full coverage.\n\nPage third only; not full coverage."
        )
        assert outputs[-1]["meaningful"] is True and sink._active == {"tool:slow-operation"}
    finally:
        sink.close()


def test_close_reaps_a_timer_waiting_for_the_callers_same_lock(monkeypatch) -> None:
    sink = ProgressiveEventSink(
        lambda _: None, user_input="Read pages", policy=PublicOutputPolicy(wait_seconds=0.01)
    )
    entered = Event()
    wait_elapsed = sink._wait_elapsed

    def elapsed(generation):
        entered.set()
        wait_elapsed(generation)

    monkeypatch.setattr(sink, "_wait_elapsed", elapsed)
    timer = None
    try:
        with sink._lock:
            sink.operation_started("slow")
            timer = sink._timer
            assert timer is not None and entered.wait(1)
            sink.close()
            assert not timer.is_alive(), "cancel alone does not stop an entered callback"
    finally:
        sink.close()
        if timer is not None:
            timer.join(1)


def test_close_waits_for_durable_emission_and_reaps_its_timer() -> None:
    entered, release, closed = Event(), Event(), Event()
    events: list[HarnessEventDraft] = []

    def append(event):
        if event.event_type is EventType.PUBLIC_OUTPUT:
            entered.set()
            assert release.wait(1), "test emitter must always be released"
        events.append(event)

    sink = ProgressiveEventSink(
        append, user_input="Read pages", policy=PublicOutputPolicy(wait_seconds=0.01)
    )
    sink.operation_started("slow")
    timer = sink._timer
    assert timer is not None

    def close():
        sink.close()
        closed.set()

    closer = Thread(target=close)
    try:
        assert entered.wait(1)
        closer.start()
        assert not closed.wait(0.05), "an authorized durable emission cannot be detached"
        release.set()
        assert closed.wait(1)
        assert not timer.is_alive()
        count = len(events)
        sink.publish("late", "commentary", "evidence", "must not publish")
        assert len(events) == count
    finally:
        release.set()
        if closer.ident is not None:
            closer.join(1)
        sink.close()


def test_close_from_inside_the_timer_emitter_does_not_join_itself() -> None:
    closed = Event()

    def append(event):
        if event.event_type is EventType.PUBLIC_OUTPUT:
            sink.close()
            closed.set()

    sink = ProgressiveEventSink(
        append, user_input="Read pages", policy=PublicOutputPolicy(wait_seconds=0.01)
    )
    sink.operation_started("slow")
    timer = sink._timer
    assert timer is not None
    try:
        assert closed.wait(1)
        sink.close()
        timer.join(1)
        assert not timer.is_alive()
    finally:
        sink.close()


@pytest.mark.parametrize("finish", ["close", "terminal", "next_request"])
def test_cancelled_fact_batch_cannot_publish_from_a_stale_callback(finish) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(
        events.append, user_input="Read pages", policy=PublicOutputPolicy(delta_seconds=0.5)
    )
    try:
        for call_id in ("first", "pending"):
            sink(
                draft(
                    EventType.TOOL_EXECUTION_COMPLETED,
                    tool_call_id=call_id,
                    status="executed",
                    metadata={"public_facts": verified_facts(f"Page {call_id} only.")},
                )
            )
        timer, generation = sink._evidence_timer, sink._evidence_generation
        assert timer is not None
        if finish == "close":
            sink.close()
        else:
            sink(
                draft(
                    EventType.ANSWER_COMMITTED
                    if finish == "terminal"
                    else EventType.MODEL_REQUEST_STARTED
                )
            )
        count = len(events)
        sink._wait_elapsed(generation, evidence=True)
        assert len(events) == count
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert len(outputs) == (2 if finish == "next_request" else 1)
        assert sink._evidence_timer is None
    finally:
        sink.close()


def test_native_publication_deadline_closes_socket_and_reaps_timer(scratch) -> None:
    """Native emitter bound, not a thread timeout; Worker wiring is verified separately."""
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_io import task_io_deadline
    from psycopg.conninfo import make_conninfo

    dsn, _ = scratch
    label = f"public-close-{uuid4().hex}"
    database = PostgresDatabase(
        make_conninfo(dsn, application_name=label), deployment_namespace="test"
    )
    entered, failed = Event(), Event()
    connections, failures = [], []

    def append(event):
        if event.event_type is EventType.PUBLIC_OUTPUT:
            try:
                with task_io_deadline(monotonic() + 0.25), database.connect_task_io() as connection:
                    connections.append(connection)
                    entered.set()
                    connection.execute("SELECT pg_sleep(5)")
            except Exception as error:
                failures.append(error)
                failed.set()
                raise

    sink = ProgressiveEventSink(
        append, user_input="Read pages", policy=PublicOutputPolicy(wait_seconds=0.01)
    )
    sink.operation_started("slow")
    timer = sink._timer
    assert timer is not None
    try:
        assert entered.wait(1)
        started = monotonic()
        with pytest.raises(TimeoutError) as caught:
            sink.close()
        assert failed.is_set() and caught.value is failures[0]
        assert monotonic() - started < 0.7
        assert not timer.is_alive() and all(connection.closed for connection in connections)
        with psycopg.connect(dsn) as observe:
            assert not observe.execute(
                "SELECT 1 FROM pg_stat_activity WHERE application_name=%s", (label,)
            ).fetchone(), "native publisher survived close"
    finally:
        with pytest.raises(TimeoutError):
            sink.close()


def test_native_connect_timeout_reaps_the_publication_timer_and_closes_peer_socket() -> None:
    from agent_storage.postgres.database import PostgresDatabase
    from psycopg.conninfo import make_conninfo

    accepted, disconnected = Event(), Event()
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(1)

        def peer():
            with server.accept()[0] as connection:
                accepted.set()
                connection.settimeout(1)
                while connection.recv(65536):
                    pass
            disconnected.set()

        receiver = Thread(target=peer)
        receiver.start()
        database = PostgresDatabase(
            make_conninfo(host="127.0.0.1", port=server.getsockname()[1], sslmode="disable"),
            deployment_namespace="test",
        )

        def append(event):
            if event.event_type is EventType.PUBLIC_OUTPUT:
                database.connect_task_io(timeout_seconds=0.25)

        sink = ProgressiveEventSink(
            append, user_input="Read pages", policy=PublicOutputPolicy(wait_seconds=0.01)
        )
        sink.operation_started("slow")
        timer = sink._timer
        assert timer is not None
        try:
            assert accepted.wait(1)
            started = monotonic()
            with pytest.raises(TimeoutError, match="Task storage"):
                sink.close()
            assert monotonic() - started < 0.7
            assert disconnected.wait(0.5), "publication native connect socket survived close"
            assert not timer.is_alive()
            receiver.join(1)
            assert not receiver.is_alive()
        finally:
            receiver.join(1)
            with pytest.raises(TimeoutError):
                sink.close()


def test_closing_during_fact_persistence_does_not_start_optional_expression() -> None:
    entered, release = Event(), Event()
    calls = []
    events: list[HarnessEventDraft] = []

    def append(event):
        if (
            event.event_type is EventType.PUBLIC_OUTPUT
            and "second" in event.payload["evidence_refs"]
        ):
            entered.set()
            assert release.wait(1)
        events.append(event)

    def complete(*_):
        calls.append("expression")
        return completion('{"order":[0,1],"lead":"none"}')

    sink = ProgressiveEventSink(
        append,
        user_input="Compare pages",
        policy=PublicOutputPolicy(),
        expression=expression(complete, events),
    )
    closer = Thread(target=sink.close)
    try:
        with sink._lock:
            for call_id in ("first", "second", "third"):
                sink(
                    draft(
                        EventType.TOOL_EXECUTION_COMPLETED,
                        tool_call_id=call_id,
                        status="executed",
                        metadata={"public_facts": verified_facts(f"Page {call_id} only.")},
                    )
                )
        assert entered.wait(1)
        closer.start()
        assert sink._closing.wait(1)
        release.set()
        closer.join(1)
        assert not closer.is_alive() and calls == []
        assert not any(event.payload.get("purpose") == "public_expression" for event in events)
    finally:
        release.set()
        if closer.ident is not None:
            closer.join(1)
        sink.close()
