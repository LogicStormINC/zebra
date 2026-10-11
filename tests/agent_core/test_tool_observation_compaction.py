import json
from datetime import UTC, datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.harness.tool_observation_compaction import compact_repeated_records


def message(content: str, role: MessageRole = MessageRole.TOOL) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(), role=role, content=content,
        created_at=datetime.now(UTC),
        tool_call_id="call" if role is MessageRole.TOOL else None,
    )


def payload(summary: str = "evidence " * 100) -> str:
    return json.dumps({"status": "ready", "query_completed": True, "total_count": 5,
                      "page": {"next_cursor": "next"}, "items": [{
                          "event_id": "event", "source_id": "source", "period_id": "period",
                          "summary": summary, "original_url": "https://example.com/evidence"}]})


def test_exact_duplicate_is_compact_but_evidence_and_query_receipts_are_retained():
    first, second = message(payload()), message(payload())
    result = compact_repeated_records([first, second])
    assert result[0] is first
    assert second.content == payload()
    data = json.loads(result[1].content)
    assert data["items"][0]["same_record_in_tool_call"] == "call"
    assert data["items"][0]["original_url"] == "https://example.com/evidence"
    assert data["total_count"] == 5 and data["page"]["next_cursor"] == "next"
    assert len(result[1].content) < len(second.content)


def test_changed_facts_new_user_turn_failures_and_malformed_json_are_not_compacted():
    first, changed = message(payload()), message(payload("different evidence " * 100))
    assert compact_repeated_records([first, changed])[1] is changed
    user = message("next question", MessageRole.USER)
    assert compact_repeated_records([first, user, first])[-1] is first
    failed = message(json.dumps({"status": "failed", "output": payload()}))
    malformed = message("not json")
    assert compact_repeated_records([first, failed, malformed]) == [first, failed, malformed]


def test_wrapped_success_is_compacted_without_mutating_metadata():
    first = message(json.dumps({"status": "executed", "output": payload(), "coverage": "partial"}))
    result = compact_repeated_records([first, first])
    data = json.loads(result[1].content)
    assert data["coverage"] == "partial"
    assert json.loads(data["output"])["items"][0]["same_record_in_tool_call"] == "call"
