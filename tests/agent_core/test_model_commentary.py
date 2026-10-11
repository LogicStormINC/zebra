"""Producer text/identity/quota contract; no fabricated business facts."""

from dataclasses import replace

import pytest
from agent_core.contracts.model_events import ModelResponseReceivedPayload
from agent_core.contracts.public_output import PublicOutputPayload, PublicOutputPolicy
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.model_commentary import commentary_outputs, plan_response, text_hash
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.progress_recovery import fold_progress_page
from agent_core.harness.public_output import ProgressiveEventSink
from agent_core.ports.task_projection_checkpoints import CheckpointConflict

from tests.agent_core.test_progress_recovery import head_and_page


def source(text="公开说明", call="model:1", attempt=1):
    return {
        "assistant_message": text,
        "response_stage": "tool_loop",
        "model_call_id": call,
        "attempt_number": attempt,
    }


@pytest.mark.parametrize("length", [1, 4000, 4001, 32000])
def test_exact_unicode_text_chunks_and_stable_identity(length):
    raw = source(("😀 中\n" * (length // 4 + 1))[:length])
    planned = plan_response(raw, 0)
    drafts = commentary_outputs(planned)
    assert "".join(str(d.payload["content"]) for d in drafts) == raw["assistant_message"]
    assert planned["public_commentary"]["source_sha256"] == text_hash(raw["assistant_message"])
    assert commentary_outputs(planned) == drafts
    for draft in drafts:
        output = PublicOutputPayload.model_validate(draft.payload)
        assert not output.meaningful and output.evidence_basis is None and not output.evidence_refs


@pytest.mark.parametrize(
    "text,reserved,disposition",
    [
        ("x" * 32001, 0, "text_limit"),
        ("x", 8, "quota_exhausted"),
        ("x" * 4001, 7, "quota_exhausted"),
    ],
)
def test_explicit_coverage_gap_preserves_entire_original(text, reserved, disposition):
    planned = plan_response(source(text), reserved)
    assert planned["assistant_message"] == text
    assert planned["public_commentary"]["disposition"] == disposition
    assert commentary_outputs(planned) == ()


@pytest.mark.parametrize(
    "stage,text",
    [
        ("candidate", "draft"),
        ("final", "final"),
        ("public_expression", "expression"),
        ("tool_loop", "Tool calls proposed."),
        ("tool_loop", "  \n"),
    ],
)
def test_only_public_tool_loop_assistant_text_is_eligible(stage, text):
    payload = {**source(text), "response_stage": stage}
    assert "public_commentary" not in plan_response(payload, 0)
    assert commentary_outputs(payload) == ()


def test_separate_quota_cannot_starve_verified_facts_and_recovery_counts():
    recorded = []
    sink = ProgressiveEventSink(
        recorded.append, user_input="read", policy=PublicOutputPolicy(max_outputs=1)
    )
    try:
        for i in range(9):
            sink(
                HarnessEventDraft(
                    EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, source(call=str(i))
                )
            )
        assert sink.publish(
            "verified",
            "result",
            "evidence",
            "Verified",
            meaningful=True,
            evidence_basis="verified_result",
            evidence_refs=["receipt:1"],
        )
        outputs = [d for d in recorded if d.event_type is EventType.PUBLIC_OUTPUT]
        assert len(outputs) == 9
        assert recorded[-2].payload["public_commentary"]["disposition"] == "quota_exhausted"
        h, page = head_and_page(*[(d.event_type, d.payload) for d in recorded])
        state = fold_progress_page(h, page, output_published=lambda _: False).head.state
        assert state.published_count == 1
        assert state.commentary_reserved_count == state.commentary_published_count == 8
        assert state.pending_commentary is None and state.meaningful
    finally:
        sink.close()


def test_pending_source_frontier_validates_exact_chunk_no_fact_claims():
    payload = plan_response(source("中" * 4001), 0)
    drafts = commentary_outputs(payload)
    h, page = head_and_page((EventType.MODEL_RESPONSE_RECEIVED, payload))
    folded = fold_progress_page(h, page, output_published=lambda _: False).head
    assert folded.state.pending_commentary.source_sequence == 1
    assert folded.state.commentary_published_count == 0
    for field, value in [
        ("content", "changed"),
        ("meaningful", True),
        ("model_call_id", "foreign"),
    ]:
        _, chunk_page = head_and_page(
            (EventType.PUBLIC_OUTPUT, {**drafts[0].payload, field: value})
        )
        entry = replace(chunk_page.events[0], task_id=h.scope.task_id, task_sequence=2)
        chunk_page = replace(chunk_page, events=(entry,), after_sequence=1, highwater=2)
        with pytest.raises((CheckpointConflict, ValueError)):
            fold_progress_page(folded, chunk_page, output_published=lambda _: False)


def test_corrupt_source_hash_and_chunk_identity_are_rejected():
    payload = plan_response(source(), 0)
    payload["assistant_message"] = "tampered"
    with pytest.raises(ValueError, match="source"):
        commentary_outputs(payload)
    payload = plan_response(source(), 0)
    payload["public_commentary"]["output_ids"] = ["unrelated"]
    with pytest.raises(ValueError, match="deterministic"):
        commentary_outputs(payload)


def test_source_contract_preserves_edge_whitespace_without_private_reasoning():
    text = " \n真实公开说明\t "
    planned = plan_response(source(text), 0)
    parsed = ModelResponseReceivedPayload.model_validate(planned)
    assert parsed.assistant_message == text
    assert parsed.public_commentary.source_sha256 == text_hash(text)
    assert "".join(str(d.payload["content"]) for d in commentary_outputs(planned)) == text
    with pytest.raises(ValueError):
        ModelResponseReceivedPayload.model_validate({**planned, "reasoning_content": "private"})
