from typing import Any

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy


def operation_facts(**changes: object) -> dict[str, Any]:
    return {
        "kind": "operation",
        "tool_call_id": "operation:1",
        "operation_completed": True,
        "evidence_basis": "verified_work",
        "output_truncated": False,
        "receipt": {
            "tool_name": "command.run",
            "execution_location": "zebra",
            "scopes": ["zebra:local"],
            "risk": "read",
            "status": "executed",
            "output_bytes": 17,
            "schema_version": "1",
        },
        **changes,
    }


def terminal(facts: object, **changes: object) -> HarnessEventDraft:
    return HarnessEventDraft(
        EventType.TOOL_EXECUTION_COMPLETED,
        EventActor.TOOL,
        {
            "tool_call_id": "operation:1",
            "tool_name": "command.run",
            "status": "executed",
            "metadata": {"public_facts": facts},
            **changes,
        },
    )


@pytest.mark.parametrize("name", ["command.run", "files.read", "host.custom.operation"])
def test_generic_receipt_work_does_not_require_a_trench_read_scope(name: str) -> None:
    events: list[HarnessEventDraft] = []
    facts = operation_facts()
    facts["receipt"]["tool_name"] = name
    sink = ProgressiveEventSink(
        events.append, user_input="Inspect workspace", policy=PublicOutputPolicy()
    )
    try:
        sink(terminal(facts, tool_name=name, arguments={"secret": "raw-private-argv"}))
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert len(outputs) == 1
        assert "evidence_basis" not in outputs[0]
        assert outputs[0]["kind"] == "commentary" and outputs[0]["meaningful"] is False
        assert outputs[0]["evidence_refs"] == ["operation:1"]
        assert "17" in outputs[0]["content"] and "business" in outputs[0]["content"]
        assert "raw-private-argv" not in str(outputs)
        assert sink.policy.expression_max_calls == 0
    finally:
        sink.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"operation_completed": False},
        {"operation_completed": 1},
        {"evidence_basis": "verified_result"},
        {"summary": "The user's business goal succeeded!"},
        {"stdout": "untrusted private body"},
        {"output_truncated": 0},
        {"tool_call_id": "\n"},
        {"tool_call_id": "x" * 161},
    ],
)
def test_operation_contract_rejects_unproven_or_private_claims(changes: dict[str, object]) -> None:
    from agent_core.contracts.public_output import PublicOperationFacts

    with pytest.raises(ValueError):
        PublicOperationFacts.model_validate(operation_facts(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unavailable"},
        {"status": "failed"},
        {"output_bytes": True},
        {"output_bytes": "17"},
        {"output_bytes": 4_194_305},
        {"scopes": []},
        {"scopes": ["same", "same"]},
        {"scopes": [17]},
        {"scopes": ["x" * 257]},
        {"scopes": ["bad\nscope"]},
        {"tool_name": "command.run\nclaim"},
    ],
)
def test_operation_contract_reuses_and_bounds_the_execution_receipt(
    changes: dict[str, object],
) -> None:
    from agent_core.contracts.public_output import PublicOperationFacts

    facts = operation_facts()
    facts["receipt"].update(changes)
    with pytest.raises(ValueError):
        PublicOperationFacts.model_validate(facts)


@pytest.mark.parametrize(
    "changes",
    [{"tool_call_id": "other-call"}, {"tool_name": "other.tool"}, {"status": "failed"}],
)
def test_operation_evidence_cannot_be_borrowed_by_another_terminal(
    changes: dict[str, object],
) -> None:
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(
        events.append, user_input="Inspect workspace", policy=PublicOutputPolicy()
    )
    try:
        sink(terminal(operation_facts(), **changes))
        sink(
            HarnessEventDraft(
                EventType.MODEL_REQUEST_STARTED, EventActor.HARNESS, {"model_call_id": "next"}
            )
        )
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert all(output.get("evidence_basis") is None for output in outputs)
        assert all(output["meaningful"] is False for output in outputs)
    finally:
        sink.close()


def test_partial_operation_receipt_cannot_claim_complete_output_or_business_results() -> None:
    from agent_core.contracts.public_output import PublicOperationFacts

    facts = PublicOperationFacts.model_validate(operation_facts(output_truncated=True))
    assert facts.receipt.scopes == ("zebra:local",)
    assert "partial" in facts.summary
    assert facts.evidence_basis == "verified_work"
    restored = PublicOperationFacts.model_validate_json(facts.model_dump_json())
    assert restored.summary == facts.summary


def test_operation_work_and_legacy_partial_read_result_keep_separate_bases() -> None:
    from agent_core.contracts.public_output import PublicReadFacts

    read = {
        "query_completed": True,
        "evidence_basis": "verified_result",
        "applied_scope": {
            "kind": "event_detail",
            "source_scope": "one_source",
            "period_scope": "one_period",
            "date_from": None,
            "date_to": None,
            "keyword_filtered": False,
            "market_filtered": False,
        },
        "summary": "Verified one source record; content is partial, not complete coverage.",
        "record_refs": [{"event_id": "source-event", "source_id": "source"}],
        "returned_count": 1,
        "total_count": 10,
        "content_partial": True,
        "partial_sample": True,
    }
    assert PublicReadFacts.model_validate(read).model_dump(include=set(read)) == read
    events: list[HarnessEventDraft] = []
    sink = ProgressiveEventSink(
        events.append, user_input="Inspect workspace", policy=PublicOutputPolicy()
    )
    try:
        sink(terminal(operation_facts()))
        sink(terminal(read, tool_call_id="read:1", tool_name="source.read"))
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert [(output["kind"], output.get("evidence_basis")) for output in outputs] == [
            ("commentary", None),
            ("result", "verified_result"),
        ]
        assert outputs[0]["meaningful"] is False
        assert outputs[1]["content"] == read["summary"]
        assert outputs[1]["evidence_refs"] == ["read:1"]
    finally:
        sink.close()


@pytest.mark.parametrize("basis", ["verified_work", "verified_result"])
def test_mixed_batches_and_aux_replacements_take_basis_only_from_displayed_read_evidence(
    basis: str,
) -> None:
    from datetime import UTC, datetime

    from agent_core.domain.identifiers import new_message_id
    from agent_core.domain.messages import MessageRole, SessionMessage
    from agent_core.domain.modeling import ModelCompletion
    from agent_core.harness.public_expression import PublicExpression

    events: list[HarnessEventDraft] = []
    reads = {
        "query_completed": True,
        "evidence_basis": basis,
        "applied_scope": {
            "kind": "event_detail",
            "source_scope": "one_source",
            "period_scope": "one_period",
            "date_from": None,
            "date_to": None,
            "keyword_filtered": False,
            "market_filtered": False,
        },
        "summary": "Verified source title: bounded evidence, not full coverage.",
        "record_refs": [{"event_id": "source-event", "source_id": "source"}],
    }
    formatter = PublicExpression(
        lambda *_: ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content='{"order":[1,0],"lead":"none"}',
                created_at=datetime.now(UTC),
            )
        ),
        events.append,
        max_calls=1,
        deadline_s=1,
        max_input_characters=1600,
        max_output_tokens=128,
    )
    sink = ProgressiveEventSink(
        events.append, user_input="Read source", policy=PublicOutputPolicy(), expression=formatter
    )
    try:
        sink(terminal(reads, tool_call_id="read:first", tool_name="source.read"))
        sink(terminal(operation_facts()))
        sink(terminal(reads, tool_call_id="read:next", tool_name="source.read"))
        sink(
            HarnessEventDraft(
                EventType.MODEL_REQUEST_STARTED, EventActor.HARNESS, {"model_call_id": "next"}
            )
        )
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        replacement = next(output for output in outputs if output.get("replaces_output_id"))
        fallback = next(
            output for output in outputs if output["output_id"] == replacement["replaces_output_id"]
        )
        assert fallback["evidence_basis"] == replacement["evidence_basis"] == basis
        assert fallback["meaningful"] is True and replacement["meaningful"] is True
        assert (
            fallback["evidence_refs"]
            == replacement["evidence_refs"]
            == ["operation:1", "read:next"]
        )
        assert (
            reads["summary"] in fallback["content"] and reads["summary"] in replacement["content"]
        )
    finally:
        sink.close()

    replay: list[HarnessEventDraft] = []
    recovered = ProgressiveEventSink(
        replay.append, user_input="Read source", policy=PublicOutputPolicy(), prior_outputs=outputs
    )
    try:
        for event in (
            terminal(operation_facts()),
            terminal(reads, tool_call_id="read:next", tool_name="source.read"),
        ):
            recovered.observe_operation_result(event)
        assert replay == []
    finally:
        recovered.close()


def test_generic_only_pending_batch_never_calls_aux_or_becomes_meaningful() -> None:
    from agent_core.harness.public_expression import PublicExpression

    events: list[HarnessEventDraft] = []
    formatter = PublicExpression(
        lambda *_: pytest.fail("generic status must not call AUX"),
        events.append,
        max_calls=1,
        deadline_s=1,
        max_input_characters=1600,
        max_output_tokens=128,
    )
    # A restored read output means new generic receipts can be collected in one pending batch.
    prior = [
        {
            "output_id": "public:read",
            "phase": "evidence",
            "evidence_basis": "verified_result",
            "meaningful": True,
            "evidence_refs": ["read:first"],
        }
    ]
    sink = ProgressiveEventSink(
        events.append,
        user_input="Read source",
        policy=PublicOutputPolicy(),
        prior_outputs=prior,
        expression=formatter,
    )
    try:
        for call_id in ("operation:1", "operation:2"):
            facts = operation_facts(tool_call_id=call_id)
            facts["receipt"]["output_bytes"] = 17 if call_id.endswith("1") else 19
            sink(terminal(facts, tool_call_id=call_id))
        sink(
            HarnessEventDraft(
                EventType.MODEL_REQUEST_STARTED, EventActor.HARNESS, {"model_call_id": "next"}
            )
        )
        outputs = [event.payload for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert len(outputs) == 1 and outputs[0]["meaningful"] is False
        assert (
            "evidence_basis" not in outputs[0]
            and "17" in outputs[0]["content"]
            and "19" in outputs[0]["content"]
        )
        assert outputs[0]["evidence_refs"] == ["operation:1", "operation:2"]
    finally:
        sink.close()
