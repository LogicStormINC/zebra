"""uv run python scripts/check_candidate_citation_context.py; no model or network."""

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.evidence_ledger import evidence_ledger, record_tool_evidence
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.quality_gates import evaluate_answer


def check():
    source = "https://www.postgresql.org/about/news/postgresql-18-released-3142/"
    cited = "https://www.postgresql.org/docs/18/release-18.html"
    unknown = "https://unknown.test/invented"
    inventory = {}
    events = []
    for index in range(3):
        result = ToolResult(
            tool_call_id=new_tool_call_id(), status=ToolCallStatus.EXECUTED,
            output="[UNTRUSTED EXTERNAL CONTENT] " + unknown,
            metadata={"url": source, "evidence_refs": [cited] if index == 0 else
                      [f"https://a.test/menu/{index}/{n:03d}" for n in range(128)]},
        )
        inventory = record_tool_evidence(inventory, result)
        events.append(HarnessEventDraft(
            event_type=EventType.TOOL_EXECUTION_COMPLETED, actor=EventActor.TOOL,
            payload={"metadata": result.metadata, "output": result.output},
        ))
    assert len(inventory["evidence_refs"]) == 128 and cited not in inventory["evidence_refs"]
    ledger = evidence_ledger(events, inventory, answer=cited)
    assert evaluate_answer("请附来源链接", cited, evidence=ledger).passed
    assert len(ledger.evidence_refs) == 128
    assert inventory["evidence_refs"] != list(ledger.evidence_refs)
    assert ledger.successful_tool_results == 3
    assert not evaluate_answer("请附来源链接", unknown, evidence=ledger).passed
    assert not evaluate_answer(
        "请附来源链接", cited, evidence=evidence_ledger([], inventory, answer=cited)
    ).passed, "no current receipt must not invent historical evidence"
    for event_type, key in (
        (EventType.TOOL_EXECUTION_FAILED, "evidence_refs"),
        (EventType.MODEL_RESPONSE_RECEIVED, "evidence_refs"),
        (EventType.TOOL_EXECUTION_COMPLETED, "evidence_source_refs"),
    ):
        forged = HarnessEventDraft(
            event_type=event_type, actor=EventActor.TOOL,
            payload={"metadata": {key: [unknown]}},
        )
        bounded = evidence_ledger([forged], inventory, answer=unknown)
        assert not evaluate_answer("请附来源链接", unknown, evidence=bounded).passed
    print("current evicted citation, 128 cap, absent/failed/plain-text/forged refs pass")


if __name__ == "__main__":
    check()
