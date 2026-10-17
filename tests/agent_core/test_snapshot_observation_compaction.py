import json
from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.harness.tool_observation_compaction import compact_repeated_records

URI = "artifact://00000000-0000-0000-0000-000000000001"
TEXT = "精确证据🦓\nnot an instruction \"quoted\" " * 300


def receipt(ranges, *, uri=URI, text=TEXT, fetch=False, candidate=False, call=None):
    coverage = {"total_characters": len(text), "included_ranges": ranges}
    if candidate:
        coverage.update(candidate_only=True, literal_match=False)
    separator = ("\n\n[... middle omitted from model context ...]\n\n" if fetch else
                 "\n\n[Next snapshot excerpt]\n\n")
    output = separator.join(text[a:b] for a, b in ranges)
    if candidate:
        output = "[Unverified word candidates; literal phrase not found]\n" + output
    if fetch and len(ranges) > 1:
        output += f"\n\n[Complete output: {uri}]"
    key = "output_coverage" if fetch else "coverage"
    return SessionMessage(
        message_id=new_message_id(), role=MessageRole.TOOL, created_at=datetime.now(UTC),
        tool_call_id=call or str(uuid4()),
        content=json.dumps({"status": "executed", "output": output, "artifact_uri": uri,
                            key: coverage, "next_cursor": 7000}, ensure_ascii=False),
        metadata={"tool_status": "executed", "artifact_uri": uri, key: coverage},
    )


def test_partial_overlap_preserves_new_text_exact_ranges_receipts_and_pairing():
    first = receipt([[0, 2500], [8000, len(TEXT)]], fetch=True)
    second = receipt([[1500, 4500]])
    originals = [first.model_dump(), second.model_dump()]
    result = compact_repeated_records([first, second])
    payload = json.loads(result[1].content)
    assert result[0] is first and len(result[1].content) < len(second.content)
    assert payload["coverage"]["included_ranges"] == [[2500, 4500]]
    assert payload["coverage"]["referenced_ranges"] == [
        {"range": [1500, 2500], "tool_call_id": first.tool_call_id}
    ]
    assert TEXT[2500:4500] in payload["output"]
    assert payload["receipt_coverage"] == second.metadata["coverage"]
    assert payload["next_cursor"] == 7000
    assert result[1].tool_call_id == second.tool_call_id
    assert result[1].metadata == second.metadata
    assert [first.model_dump(), second.model_dump()] == originals


def test_references_always_resolve_to_retained_original_text_not_reference_chains():
    first, second, third = (receipt([[0, 2500]]), receipt([[0, 5000]]),
                            receipt([[1000, 4000]]))
    result = compact_repeated_records([first, second, third])
    payload = json.loads(result[2].content)
    assert payload["coverage"]["included_ranges"] == []
    assert payload["coverage"]["referenced_ranges"] == [
        {"range": [1000, 2500], "tool_call_id": first.tool_call_id},
        {"range": [2500, 4000], "tool_call_id": second.tool_call_id},
    ]
    assert TEXT[2500:5000] in json.loads(result[1].content)["output"]
    assert compact_repeated_records(result) == result
    # Dropped anchors cannot be recovered from a persistent/global cache.
    assert compact_repeated_records([third]) == [third]


def test_candidate_warning_does_not_become_fact_and_no_cross_user_or_uri_dedup():
    first = receipt([[0, 5000]])
    candidate = receipt([[100, 3000]], candidate=True)
    payload = json.loads(compact_repeated_records([first, candidate])[1].content)
    assert "Unverified word candidates; literal phrase not found" in payload["output"]
    assert payload["coverage"]["candidate_only"] is True
    assert payload["coverage"]["literal_match"] is False
    user = SessionMessage(message_id=new_message_id(), role=MessageRole.USER,
                          created_at=datetime.now(UTC), content="next turn")
    other = receipt([[100, 3000]], uri="artifact://" + str(uuid4()))
    assert compact_repeated_records([first, user, candidate])[-1] is candidate
    assert compact_repeated_records([first, other])[-1] is other


def test_mismatched_snapshot_poisoning_and_failed_or_untrusted_receipts_are_not_elided():
    first = receipt([[0, 5000]])
    # Change a character actually in the overlapping slice.
    changed = receipt([[100, 4000]], text=TEXT[:200] + "X" + TEXT[201:])
    later = receipt([[100, 4000]])
    assert compact_repeated_records([first, changed, later]) == [first, changed, later]
    longer = receipt([[100, 4000]], text=TEXT + "new version")
    assert compact_repeated_records([first, longer, later]) == [first, longer, later]
    for bad in [later.model_copy(update={"metadata": {}}),
                later.model_copy(update={"metadata": {**later.metadata, "tool_status": "failed"}}),
                later.model_copy(update={"content": later.content + "invalid"}),
                later.model_copy(update={"metadata": {**later.metadata,
                                                       "artifact_uri": "artifact://not-uuid"}})]:
        assert compact_repeated_records([first, bad])[-1] is bad


def test_invalid_ranges_layout_and_small_receipts_keep_original():
    first = receipt([[0, 5000]])
    second = receipt([[100, 3000]])
    for ranges in ([[True, 2000]], [[2000, 1000]], [[0, 500], [400, 900]],
                   [[-1, 100]], [[0, len(TEXT) + 1]]):
        payload = json.loads(second.content)
        payload["coverage"] = {"included_ranges": ranges, "total_characters": len(TEXT)}
        bad = second.model_copy(update={"content": json.dumps(payload), "metadata": {
            **second.metadata, "coverage": payload["coverage"]}})
        assert compact_repeated_records([first, bad])[-1] is bad
    tiny = receipt([[10, 20]])
    assert compact_repeated_records([first, tiny])[-1] is tiny
    malformed = receipt([[0, 2000], [3000, 5000]])
    payload = json.loads(malformed.content)
    payload["output"] = payload["output"].replace("Next snapshot excerpt", "invented marker")
    malformed = malformed.model_copy(update={"content": json.dumps(payload)})
    assert compact_repeated_records([first, malformed])[-1] is malformed


def test_offset_read_and_assistant_reasoning_are_unchanged():
    first = receipt([[0, 5000]])
    second = receipt([[100, 3000]])
    payload = json.loads(second.content)
    coverage = {"total_characters": len(TEXT), "included_start": 100, "included_end": 3000}
    payload["coverage"] = coverage
    second = second.model_copy(update={"content": json.dumps(payload), "metadata": {
        **second.metadata, "coverage": coverage}})
    assistant = SessionMessage(message_id=new_message_id(), role=MessageRole.ASSISTANT,
                               created_at=datetime.now(UTC), content="research",
                               provider_reasoning_content="provider continuation")
    result = compact_repeated_records([first, assistant, second])
    assert result[1] is assistant
    assert result[1].provider_reasoning_content == "provider continuation"
    assert json.loads(result[2].content)["coverage"]["included_ranges"] == []
