import json
from pathlib import Path

from agent_observability import load_eval_cases


def test_handoff_eval_matrix_covers_release_risks() -> None:
    root = Path("evals/session_handoff")
    cases = load_eval_cases(root)
    payloads = {
        path.stem: json.loads(path.read_text(encoding="utf-8")) for path in root.glob("*.json")
    }

    assert {case.case_id for case in cases} == {
        "handoff-continuity",
        "handoff-no-replay",
        "handoff-authority-narrowing",
        "handoff-workspace-drift",
        "handoff-depth-limit",
        "handoff-concurrency",
        "handoff-crash-recovery",
    }
    assert payloads["continuity"]["provider_smoke"] is True
    assert all(case.max_cost_usd is not None for case in cases)
    combined = " ".join(case.prompt.lower() for case in cases)
    for required in ("authority", "drift", "depth", "race", "crash", "replay"):
        assert required in combined


def test_provider_smoke_never_embeds_credentials() -> None:
    source = Path("evals/providers/session_handoff_smoke.py").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=" not in source
    assert "OPENAI_API_KEY=" not in source
    assert "provider credential unavailable" in source
