from datetime import UTC, datetime
from threading import Event
from typing import cast

import pytest
from agent_core.contracts.events import validate_event_payload
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.modeling import ModelTextDelta
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.harness.stream_deltas import TextDeltaCoalescer


def draft(kind: EventType, **payload: object) -> HarnessEventDraft:
    return HarnessEventDraft(kind, EventActor.HARNESS, payload)


def verified_facts(summary: str) -> dict[str, object]:
    return {
        "query_completed": True,
        "evidence_basis": "verified_result",
        "summary": summary,
        "applied_scope": {
            "kind": "subscription_history",
            "source_scope": "all_entitled",
            "period_scope": "all_entitled",
            "date_from": None,
            "date_to": None,
            "keyword_filtered": False,
            "market_filtered": False,
        },
        "record_refs": [{"event_id": "event-1", "source_id": "source-1"}],
    }


def test_public_output_contract_rejects_unbounded_or_private_fields() -> None:
    payload = dict(
        schema_version=1,
        attempt_number=1,
        output_id="out:1",
        kind="commentary",
        phase="evidence",
        origin="system",
        content="Read 2 records.",
        status="complete",
    )
    assert validate_event_payload(EventType.PUBLIC_OUTPUT, payload)["output_id"] == "out:1"
    for changes in ({"content": "x" * 4001}, {"output_id": " "}, {"reasoning": "private"}):
        with pytest.raises(ValueError):
            validate_event_payload(EventType.PUBLIC_OUTPUT, {**payload, **changes})


def test_tool_only_model_gets_truthful_milestones_and_replay_dedup() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(
        events.append, user_input="总结今天订阅", policy=PublicOutputPolicy()
    )
    sink(
        draft(
            EventType.MODEL_RESPONSE_RECEIVED,
            assistant_message="Tool calls proposed.",
            tool_call_count=1,
        )
    )
    sink(draft(EventType.TOOL_EXECUTION_STARTED, tool_call_id="tool:1", tool_name="source.read"))
    sink(
        draft(
            EventType.TOOL_EXECUTION_COMPLETED,
            tool_call_id="tool:1",
            status="executed",
            metadata={"public_facts": verified_facts("本页返回 15 条记录，尚未读取其余页面。")},
        )
    )
    sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="model:2"))
    sink.close()
    outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
    assert [item["phase"] for item in outputs] == ["started", "evidence"]
    assert "source.read" in str(outputs[0]["content"])
    assert outputs[0]["meaningful"] is False
    assert "15" in str(outputs[1]["content"])
    assert outputs[1]["evidence_refs"] == ["tool:1"]
    replayed: list[HarnessEventDraft] = []
    recovered = ProgressiveEventSink(
        replayed.append,
        user_input="总结今天订阅",
        policy=PublicOutputPolicy(),
        prior_outputs=outputs,
    )
    recovered(
        draft(EventType.TOOL_EXECUTION_STARTED, tool_call_id="tool:1", tool_name="source.read")
    )
    recovered(
        draft(
            EventType.TOOL_EXECUTION_COMPLETED,
            tool_call_id="tool:1",
            status="executed",
            metadata={"public_facts": verified_facts("本页返回 15 条记录，尚未读取其余页面。")},
        )
    )
    recovered(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="model:2"))
    recovered.close()
    assert not [event for event in replayed if event.event_type is EventType.PUBLIC_OUTPUT]


@pytest.mark.parametrize("name", [None, "bad\nname", "**injected**", "x" * 129])
def test_proposed_opening_is_truthful_and_never_exposes_arguments(name: object) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="查视频", policy=PublicOutputPolicy())
    sink(
        draft(
            EventType.TOOL_CALL_PROPOSED,
            tool_call_id="tool:1",
            tool_name=name,
            arguments={"token": "private-argument"},
        )
    )
    sink.close()
    output = events[-1].payload
    assert output["phase"] == "started" and output["meaningful"] is False
    assert "已提出" in str(output["content"])
    assert "已开始" not in str(output["content"])
    assert "private-argument" not in str(output)


@pytest.mark.parametrize("kind", [EventType.TOOL_CALL_PROPOSED, EventType.TOOL_EXECUTION_STARTED])
@pytest.mark.parametrize("user_input", ["查视频", "Find videos"])
def test_safe_tool_name_alone_is_not_meaningful(kind: EventType, user_input: str) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input=user_input, policy=PublicOutputPolicy())
    try:
        sink(
            draft(
                kind,
                tool_call_id="tool:1",
                tool_name="source.search",
                arguments={"query": "private-argument"},
            )
        )
        opening = events[-1].payload
        assert opening["meaningful"] is False
        assert opening["kind"] == "commentary" and opening["phase"] == "started"
        assert "source.search" in str(opening["content"])
        assert "private-argument" not in str(opening)
        assert bool(sink._active) is (kind is EventType.TOOL_EXECUTION_STARTED)
        assert (sink._timer is not None) is (kind is EventType.TOOL_EXECUTION_STARTED)
    finally:
        sink.close()


@pytest.mark.parametrize("kind", [EventType.TOOL_CALL_PROPOSED, EventType.TOOL_EXECUTION_STARTED])
def test_first_fact_is_immediate_after_generic_tool_commentary(kind: EventType) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="查视频", policy=PublicOutputPolicy())
    try:
        sink(draft(kind, tool_call_id="tool:1", tool_name="source.search"))
        if kind is EventType.TOOL_EXECUTION_STARTED:
            assert sink._timer is not None
            sink._timer.cancel()
            sink._wait_elapsed(sink._timer_generation)
            assert events[-1].payload["phase"] == "waiting"
            assert events[-1].payload["meaningful"] is False
        # A successful receipt without business facts must not consume first-evidence admission.
        sink(draft(EventType.TOOL_EXECUTION_COMPLETED, tool_call_id="empty", status="executed"))
        before_fact = len(events)
        summary = "已返回本页 3 条视频，未读取其余页面。"
        sink(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id="tool:1",
                status="executed",
                metadata={"public_facts": verified_facts(summary)},
            )
        )
        assert len(events) == before_fact + 2  # Receipt, then evidence; no next model call needed.
        assert events[-1].event_type is EventType.PUBLIC_OUTPUT
        assert events[-1].payload["kind"] == "result"
        assert events[-1].payload["phase"] == "evidence"
        assert events[-1].payload["meaningful"] is True
        assert events[-1].payload["content"] == summary
        assert events[-1].payload["evidence_refs"] == ["empty", "tool:1"]
        assert not sink._active and sink._timer is None
    finally:
        sink.close()


@pytest.mark.parametrize("prior_meaningful", [False, True])
def test_recovered_tool_opening_keeps_first_fact_immediate(prior_meaningful: bool) -> None:
    original: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(original.append, user_input="hello", policy=PublicOutputPolicy())
    sink(draft(EventType.TOOL_CALL_PROPOSED, tool_call_id="tool:1", tool_name="source.search"))
    sink.close()
    # Legacy openings may have the old flag: do not rewrite history or repeat the milestone.
    prior = {**original[-1].payload, "meaningful": prior_meaningful}
    events: list[HarnessEventDraft] = []
    recovered = ProgressiveEventSink(
        events.append, user_input="hello", policy=PublicOutputPolicy(), prior_outputs=[prior]
    )
    try:
        recovered(draft(EventType.TOOL_EXECUTION_STARTED, tool_call_id="tool:1"))
        assert [event.event_type for event in events] == [EventType.TOOL_EXECUTION_STARTED]
        assert recovered._timer is not None
        recovered._timer.cancel()
        recovered._wait_elapsed(recovered._timer_generation)
        recovered(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id="tool:1",
                status="executed",
                metadata={
                    "public_facts": verified_facts("Read this page only; more pages remain.")
                },
            )
        )
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert [output["phase"] for output in outputs] == ["waiting", "evidence"]
        assert [output["meaningful"] for output in outputs] == [False, True]
        assert outputs[-1]["content"] == "Read this page only; more pages remain."
        assert outputs[-1]["evidence_refs"] == ["tool:1"]
        assert not recovered._active and recovered._timer is None
    finally:
        recovered.close()


def test_direct_answer_has_no_preamble_and_failure_does_not_claim_retry() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="hello", policy=PublicOutputPolicy())
    sink(draft(EventType.MODEL_RESPONSE_RECEIVED, assistant_message="Hello", tool_call_count=0))
    sink(draft(EventType.ANSWER_COMMITTED, assistant_message="Hello"))
    assert not [e for e in events if e.event_type is EventType.PUBLIC_OUTPUT]
    sink.close()
    sink = ProgressiveEventSink(events.append, user_input="hello", policy=PublicOutputPolicy())
    sink(
        draft(
            EventType.TOOL_EXECUTION_FAILED, tool_call_id="write:1", metadata={"reason": "timeout"}
        )
    )
    failure = events[-1].payload
    assert failure["phase"] == "recovery"
    assert "not retry" in str(failure["content"])
    sink.close()


def test_wait_timer_reports_no_new_result_and_stops_at_close() -> None:
    published = Event()
    events: list[HarnessEventDraft] = []

    def append(event: HarnessEventDraft) -> None:
        events.append(event)
        if event.event_type is EventType.PUBLIC_OUTPUT:
            published.set()

    sink = ProgressiveEventSink(
        append, user_input="hello", policy=PublicOutputPolicy(wait_seconds=0.02)
    )
    sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="slow:1"))
    assert published.wait(1)
    sink.close()
    assert events[-1].payload["kind"] == "status"
    assert events[-1].payload["meaningful"] is False
    count = len(events)
    sink(draft(EventType.MODEL_RESPONSE_RECEIVED, assistant_message="done", tool_call_count=0))
    assert len(events) == count + 1


def test_delta_timer_flushes_during_provider_silence_without_next_chunk() -> None:
    published = Event()
    events: list[HarnessEventDraft] = []

    def append(event: HarnessEventDraft) -> None:
        events.append(event)
        if len(events) == 2:
            published.set()

    coalescer = TextDeltaCoalescer(append, attempt_number=1, characters=256, seconds=0.02)
    coalescer.emit("model:1", ModelTextDelta(0, "first"))
    coalescer.emit("model:1", ModelTextDelta(1, "buffered"))
    assert published.wait(1)
    coalescer.flush()
    assert [e.payload["content_delta"] for e in events] == ["first", "buffered"]


def test_large_deltas_cannot_grow_pending_memory_without_bounds() -> None:
    events: list[HarnessEventDraft] = []
    coalescer = TextDeltaCoalescer(events.append, attempt_number=1, characters=None, seconds=10)
    coalescer.emit("model:1", ModelTextDelta(0, "first"))
    coalescer.emit("model:1", ModelTextDelta(1, "a" * 40_000))
    coalescer.emit("model:1", ModelTextDelta(2, "b" * 40_000))
    coalescer.flush()
    assert [len(e.payload["content_delta"]) for e in events] == [5, 40_000, 40_000]
    with pytest.raises(ValueError, match="buffer limit"):
        coalescer.emit("model:1", ModelTextDelta(3, "x" * 65_537))


def test_terminal_commit_cancels_wait_and_rejects_late_output() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="hello", policy=PublicOutputPolicy())
    sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="model:1"))
    generation = sink._timer_generation
    sink(draft(EventType.ANSWER_COMMITTED, assistant_message="done"))
    sink._wait_elapsed(generation)
    sink.publish("late", "result", "evidence", "Late result", meaningful=True)
    assert not [e for e in events if e.event_type is EventType.PUBLIC_OUTPUT]
    assert sink._timer is None


def test_managed_write_receipt_yields_public_evidence_without_reexecuting_tool() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="hello", policy=PublicOutputPolicy())
    sink(
        draft(
            EventType.TESTS_COMPLETED,
            metadata={
                "execution_receipt": {
                    "tool_call_id": "write:1",
                    "status": "executed",
                    "public_facts": verified_facts("Receipt confirms one verified report."),
                }
            },
        )
    )
    sink.close()
    assert [e.event_type for e in events] == [EventType.TESTS_COMPLETED, EventType.PUBLIC_OUTPUT]
    assert events[-1].payload["evidence_refs"] == ["write:1"]
    assert events[-1].payload["meaningful"] is True


def test_public_output_is_replayable_agui_with_sequence() -> None:
    from ag_ui.core import CustomEvent
    from agent_core.domain.events import SessionEvent
    from agent_core.domain.identifiers import new_session_id
    from agent_integrations.ag_ui.contracts import AgUiRunIdentity
    from agent_integrations.ag_ui.projection import AgUiProjector

    session_id = new_session_id()
    event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.PUBLIC_OUTPUT,
        actor=EventActor.HARNESS,
        created_at=datetime.now(UTC),
        payload=dict(
            schema_version=1,
            attempt_number=1,
            output_id="public:1",
            kind="result",
            phase="evidence",
            origin="system",
            content="Read 2 records.",
            status="complete",
            meaningful=True,
            evidence_basis="verified_result",
            evidence_refs=["read:1"],
        ),
    )
    projected = AgUiProjector().project(
        [event], AgUiRunIdentity(session_id=session_id, thread_id="thread", run_id="run")
    )
    output = projected.events[-1]
    assert isinstance(output, CustomEvent)
    assert output.name == "zebra.public_output"
    assert output.value["sequence"] == 0
    assert output.value["event_id"] == str(event.event_id)
    assert output.value["evidence_basis"] == "verified_result"
    assert output.value["evidence_refs"] == ["read:1"]


def test_recovered_receipts_are_deduplicated_individually_across_batch_shapes() -> None:
    original: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(original.append, user_input="hello", policy=PublicOutputPolicy())
    for call_id in ("a", "b"):
        sink(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id=call_id,
                status="executed",
                metadata={"public_facts": verified_facts(f"Page {call_id} only.")},
            )
        )
        sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id=f"model:{call_id}"))
    sink.close()
    outputs = [e.payload for e in original if e.event_type is EventType.PUBLIC_OUTPUT]
    replay: list[HarnessEventDraft] = []
    recovered = ProgressiveEventSink(
        replay.append, user_input="hello", policy=PublicOutputPolicy(), prior_outputs=outputs
    )
    for call_id in ("a", "b", "c"):
        recovered(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id=call_id,
                status="executed",
                metadata={"public_facts": verified_facts(f"Page {call_id} only.")},
            )
        )
    recovered(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="new"))
    recovered.close()
    current = [e.payload for e in replay if e.event_type is EventType.PUBLIC_OUTPUT]
    assert len(current) == 1
    assert current[0]["evidence_refs"] == ["c"]
    assert current[0]["content"] == "Page c only."


def test_model_delta_resets_quiet_timer_but_keeps_request_active_until_response() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="hello", policy=PublicOutputPolicy())
    sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="model:1"))
    generation = sink._timer_generation
    sink(draft(EventType.MODEL_RESPONSE_DELTA, model_call_id="model:1", content_delta="First"))
    sink._wait_elapsed(generation)  # stale timer cannot narrate over fresh output
    assert not [e for e in events if e.event_type is EventType.PUBLIC_OUTPUT]
    sink._wait_elapsed(sink._timer_generation)
    assert events[-1].payload["phase"] == "waiting"
    sink(
        draft(EventType.MODEL_RESPONSE_RECEIVED, model_call_id="model:1", assistant_message="done")
    )
    assert not sink._active and sink._timer is None
    sink.close()


def test_expression_never_runs_without_persisted_fallback_and_remaining_output_budget() -> None:
    from agent_core.harness.public_expression import PublicExpression

    events: list[HarnessEventDraft] = []
    formatter = PublicExpression(
        lambda *_: pytest.fail("budget exhausted before expression"),
        events.append,
        max_calls=2,
        deadline_s=1,
        max_input_characters=1600,
        max_output_tokens=128,
    )
    sink = ProgressiveEventSink(
        events.append,
        user_input="hello",
        policy=PublicOutputPolicy(max_outputs=1),
        expression=formatter,
    )
    for call_id in ("a", "b", "c"):
        sink(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id=call_id,
                status="executed",
                metadata={"public_facts": verified_facts(f"Page {call_id} only.")},
            )
        )
    sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="next"))
    sink.close()
    assert [e.payload["content"] for e in events if e.event_type is EventType.PUBLIC_OUTPUT] == [
        "Page a only."
    ]


def test_admitted_managed_effect_waits_without_duplicate_start_event() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="hello", policy=PublicOutputPolicy())
    sink.operation_started("effect:1")  # intent was committed by the fenced dispatch store
    sink._wait_elapsed(sink._timer_generation)
    assert len(events) == 1 and events[0].event_type is EventType.PUBLIC_OUTPUT
    assert events[0].payload["phase"] == "waiting"
    sink(
        draft(
            EventType.TESTS_COMPLETED,
            metadata={
                "execution_receipt": {
                    "tool_call_id": "effect:1",
                    "status": "executed",
                    "public_facts": None,
                }
            },
        )
    )
    assert not sink._active and sink._timer is None
    sink.close()


@pytest.mark.parametrize("status", ["executed", "failed"])
def test_external_terminal_observation_does_not_append_another_tool_event(status: str) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="hello", policy=PublicOutputPolicy())
    sink.operation_started("effect:1")
    terminal = draft(
        EventType.TOOL_EXECUTION_COMPLETED
        if status == "executed"
        else EventType.TOOL_EXECUTION_FAILED,
        tool_call_id="effect:1",
        status=status,
        metadata={"public_facts": verified_facts("Read the first page only.")},
    )
    sink.observe_operation_result(terminal)
    sink.observe_operation_result(terminal)
    assert not sink._active and sink._timer is None
    assert len(events) == 1 and events[0].event_type is EventType.PUBLIC_OUTPUT
    sink.close()
    sink.observe_operation_result(terminal)
    assert len(events) == 1


def test_external_observation_rejects_nonterminal_events_without_appending() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="hello", policy=PublicOutputPolicy())
    try:
        with pytest.raises(ValueError, match="terminal tool result"):
            sink.observe_operation_result(draft(EventType.ANSWER_COMMITTED))
        assert events == []
    finally:
        sink.close()


def test_count_only_receipt_is_not_task_specific_verified_communication() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(
        events.append, user_input="总结今天订阅", policy=PublicOutputPolicy()
    )
    try:
        sink(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id="count-only",
                status="executed",
                metadata={
                    "public_facts": {"summary": "已返回 15 条读取结果。", "returned_count": 15}
                },
            )
        )
        sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="next"))
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert outputs and all(output["meaningful"] is False for output in outputs)
        assert all(output.get("evidence_basis") is None for output in outputs)
        assert all(output["kind"] != "result" for output in outputs)
    finally:
        sink.close()


@pytest.mark.parametrize("basis", ["verified_work", "verified_result"])
def test_verified_receipt_basis_requires_applied_scope_and_preserves_provenance(basis: str) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(
        events.append, user_input="总结今天订阅", policy=PublicOutputPolicy()
    )
    facts = {
        "query_completed": True,
        "evidence_basis": basis,
        "applied_scope": {
            "kind": "subscription_history",
            "source_scope": "all_entitled",
            "period_scope": "all_entitled",
            "date_from": 100,
            "date_to": 200,
            "keyword_filtered": False,
            "market_filtered": False,
        },
        "summary": "已核对当前订阅历史范围；本页内容不代表完整覆盖。",
        "record_refs": [{"event_id": "event-1", "source_id": "source-1"}]
        if basis == "verified_result"
        else [],
    }
    try:
        sink(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id="verified:1",
                status="executed",
                metadata={"public_facts": facts},
                arguments={"token": "private-raw-argument"},
            )
        )
        output = events[-1].payload
        assert events[-1].event_type is EventType.PUBLIC_OUTPUT
        assert output["evidence_basis"] == basis and output["meaningful"] is True
        assert output["kind"] == ("result" if basis == "verified_result" else "commentary")
        assert output["content"] == facts["summary"]
        assert output["evidence_refs"] == ["verified:1"] and "private" not in str(output)
        assert validate_event_payload(EventType.PUBLIC_OUTPUT, output)["evidence_basis"] == basis
    finally:
        sink.close()


def test_positive_count_only_needs_an_explicit_count_query_contract() -> None:
    from agent_core.contracts.public_output import PublicReadFacts

    facts = {**verified_facts("当前已执行查询匹配31条记录。"), "record_refs": [], "total_count": 31}
    with pytest.raises(ValueError, match="count"):
        PublicReadFacts.model_validate(facts)
    count_facts = PublicReadFacts.model_validate({**facts, "query_result_kind": "count"})
    assert count_facts.evidence_basis == "verified_result" and count_facts.total_count == 31


@pytest.mark.parametrize("user_input", ["总结订阅", "Summarize subscriptions"])
@pytest.mark.parametrize("count", [1, 3])
def test_unproven_receipt_batch_counts_published_refs(user_input: str, count: int) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input=user_input, policy=PublicOutputPolicy())
    try:
        for index in range(count):
            receipt = draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id=f"legacy:{index}",
                status="executed",
            )
            sink(receipt)
            sink(receipt)  # Duplicate delivery is still one receipt, not another success.
        sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="next"))
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert len(outputs) == 1
        assert outputs[0]["evidence_refs"] == [f"legacy:{index}" for index in range(count)]
        assert f" {count} " in str(outputs[0]["content"])
        assert outputs[0]["meaningful"] is False and "evidence_basis" not in outputs[0]
    finally:
        sink.close()


def test_mixed_receipt_batch_preserves_each_basis_and_unique_refs() -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(
        events.append, user_input="Read subscriptions", policy=PublicOutputPolicy()
    )
    try:
        # First work and result publish immediately; subsequent receipts form a mixed batch.
        for call_id, initial in (
            ("work:first", "verified_work"),
            ("result:first", "verified_result"),
        ):
            sink(
                draft(
                    EventType.TOOL_EXECUTION_COMPLETED,
                    tool_call_id=call_id,
                    status="executed",
                    metadata={
                        "public_facts": {**verified_facts(call_id), "evidence_basis": initial}
                    },
                )
            )
        for call_id, basis in (
            ("work:next", "verified_work"),
            ("result:next", "verified_result"),
            ("legacy:next", None),
        ):
            receipt = draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id=call_id,
                status="executed",
                metadata={"public_facts": {**verified_facts(call_id), "evidence_basis": basis}}
                if basis
                else {},
            )
            sink(receipt)
            sink(receipt)
        sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="next"))
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert [(item["kind"], item["evidence_basis"]) for item in outputs] == [
            ("commentary", "verified_work"),
            ("result", "verified_result"),
            ("commentary", "verified_work"),
            ("result", "verified_result"),
        ]
        assert outputs[2]["evidence_refs"] == ["work:next", "legacy:next"]
        assert outputs[2]["content"] == "work:next"
        assert outputs[3]["evidence_refs"] == ["result:next"]
        refs = [ref for output in outputs for ref in output["evidence_refs"]]
        assert len(refs) == len(set(refs)) == 5
    finally:
        sink.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"query_completed": 1},
        {"query_completed": False},
        {"record_refs": [], "total_count": True},
        {"record_refs": [], "body": "private legacy body"},
        {"applied_scope": {"kind": "subscription_history"}},
        {
            "applied_scope": cast(dict[str, object], verified_facts("source")["applied_scope"])
            | {"kind": "filesystem"}
        },
    ],
)
def test_invalid_or_body_only_facts_cannot_publish_verified_output(
    changes: dict[str, object],
) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(events.append, user_input="研究来源", policy=PublicOutputPolicy())
    try:
        sink(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id="read:invalid",
                status="executed",
                metadata={"public_facts": {**verified_facts("来源记录"), **changes}},
            )
        )
        sink(draft(EventType.MODEL_REQUEST_STARTED, model_call_id="next"))
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert outputs and all(output["meaningful"] is False for output in outputs)
        assert all(output.get("evidence_basis") is None for output in outputs)
        assert "private legacy body" not in str(outputs)
    finally:
        sink.close()
