from pathlib import Path

from agent_observability import load_eval_cases


def test_deepseek_provider_eval_matrix_is_loadable() -> None:
    cases = load_eval_cases(Path("evals/providers"))

    assert {case.case_id for case in cases} == {
        "deepseek-reasoning-privacy",
        "deepseek-stream-retry-boundary",
        "deepseek-tool-protocol",
    }
    assert {case.category for case in cases} == {"provider"}
