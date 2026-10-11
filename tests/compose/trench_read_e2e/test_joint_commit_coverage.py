"""No canonical commentary gap can disappear behind a Host meta exclusion."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_core.domain.events import EventType
from agent_core.harness.model_commentary import commentary_outputs, plan_response
from joint_commit_coverage import CommentaryCoverage, require_commentary_coverage

from tests.agent_core.test_model_commentary import source


def entry(kind, payload, seq=10):
    return SimpleNamespace(
        task_sequence=seq, event=SimpleNamespace(event_type=kind, event_id=uuid4(), payload=payload)
    )


@pytest.mark.parametrize("text,reserved", [("x", 8), ("x" * 32001, 0)])
def test_unadmitted_source_is_incomplete_even_without_host_publication(text, reserved):
    coverage = CommentaryCoverage()
    coverage.observe(
        entry(EventType.MODEL_RESPONSE_RECEIVED, plan_response(source(text), reserved))
    )
    assert not coverage.report()["complete"]
    assert coverage.report()["invalids"]
    with pytest.raises(ValueError):
        require_commentary_coverage({"commentary_coverage": coverage.report(), "records": []})


def test_missing_exact_planned_chunk_never_complete_or_silently_omitted():
    coverage = CommentaryCoverage()
    payload = plan_response(source("x" * 4001), 0)
    coverage.observe(entry(EventType.MODEL_RESPONSE_RECEIVED, payload))
    chunks = commentary_outputs(payload)
    coverage.observe(entry(EventType.PUBLIC_OUTPUT, chunks[0].payload, 11))
    assert coverage.report()["missing_output_ids"] == [chunks[1].payload["output_id"]]
    assert not coverage.report()["complete"]
    coverage.observe(entry(EventType.PUBLIC_OUTPUT, chunks[1].payload, 12))
    native = {
        "commentary_coverage": coverage.report(),
        "records": [
            {"event_type": "public_output", "output_id": d.payload["output_id"]} for d in chunks
        ],
    }
    require_commentary_coverage(native)
    native["records"].pop()
    with pytest.raises(ValueError, match="native_visibility"):
        require_commentary_coverage(native)


def test_legacy_commentary_and_tampered_chunk_remain_fail_closed():
    coverage = CommentaryCoverage()
    coverage.observe(entry(EventType.MODEL_RESPONSE_RECEIVED, source()))
    assert not coverage.report()["complete"]
    coverage = CommentaryCoverage()
    planned = plan_response(source(), 0)
    coverage.observe(entry(EventType.MODEL_RESPONSE_RECEIVED, planned))
    coverage.observe(
        entry(
            EventType.PUBLIC_OUTPUT,
            {**commentary_outputs(planned)[0].payload, "content": "changed"},
        )
    )
    assert not coverage.report()["complete"]
