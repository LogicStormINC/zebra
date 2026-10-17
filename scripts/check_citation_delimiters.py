"""Assert prose delimiters do not create invented URLs; no model/network/framework."""

from agent_core.harness.evidence_ledger import EvidenceLedger
from agent_core.harness.quality_gates import evaluate_answer

GOAL = "核对事实，附来源链接"
URL = "https://example.org/release?version=18"
ENCODED = "https://example.org/a%EF%BC%89b"
LEDGER = EvidenceLedger(successful_tool_results=1, evidence_refs=(URL, ENCODED))


def check() -> None:
    for text in (
        f"官方文档（{URL}），要点如下：已核对。",
        f"官方来源（{URL}）。",
        f"Official source ({URL}).",
        f"[官方来源]({URL})",
        f"来源：{URL}",
        f"来源：{URL}（并发细节见该页）。",
        f"来源：{URL}（章节说明），已核对。",
        f"来源（{ENCODED}），已核对。",
    ):
        result = evaluate_answer(GOAL, text, evidence=LEDGER)
        assert result.passed, (text, result)
    for url in (URL + "0", URL + "&extra=1", URL + "#uncollected", "https://other.org/release"):
        for text in (f"来源（{url}），已核对。", f"[来源]({url})"):
            result = evaluate_answer(GOAL, text, evidence=LEDGER)
            assert not result.passed, (text, result)
            assert "citation_uses_exact_collected_url" in result.missing_requirements
    for text in (
        f"[来源]({URL}（补充说明）)",
        f"[来源](  {URL}（补充说明）)",
        f"<{URL}（补充说明）>",
        f'<a href="{URL}（补充说明）">来源</a>',
    ):
        assert not evaluate_answer(GOAL, text, evidence=LEDGER).passed, text
    unicode_url = "https://example.org/标题（修订）"
    assert evaluate_answer(
        GOAL, f"[来源]({unicode_url})",
        evidence=EvidenceLedger(successful_tool_results=1, evidence_refs=(unicode_url,)),
    ).passed
    assert not evaluate_answer(GOAL, f"来源（{URL}）", evidence=EvidenceLedger()).passed
    print("PASS: prose parentheses; exact explicit destinations; "
          "unknown URLs; Unicode URL; evidence")


if __name__ == "__main__":
    check()
