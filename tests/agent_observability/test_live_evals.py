from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from agent_observability.live_eval_attempts import (
    AssertionResult,
    LiveEvalAttempt,
    digest_json,
    load_live_eval_attempts,
)
from agent_observability.live_eval_cases import (
    LiveEvalCase,
    LiveEvalFixture,
    LiveEvalInput,
    LiveEvalPostcondition,
    load_live_eval_cases,
)
from agent_observability.live_evals import build_live_eval_report

from scripts.live_eval_efficiency_report import _load_model_metrics
from scripts.live_eval_fixture import materialize
from scripts.live_eval_report import _runner_failure_summary
from scripts.live_eval_verifier import _verify_case

ROOT = Path(__file__).parents[2]
CASES_PATH = ROOT / "evals" / "live" / "cases"


def test_fixed_suite_has_sixty_balanced_explicit_cases() -> None:
    cases = load_live_eval_cases(CASES_PATH)
    categories = {
        "answer",
        "research",
        "code",
        "file",
        "operation",
        "memory_recovery",
    }

    assert len(cases) == 60
    assert {case.category for case in cases} == categories
    for category in categories:
        category_cases = [case for case in cases if case.category == category]
        assert len(category_cases) == 10
        assert sum(case.split == "development" for case in category_cases) == 6
        assert sum(case.split == "holdout" for case in category_cases) == 4
    assert all(case.repetitions == 3 for case in cases)
    assert all(case.fixture.inputs for case in cases)
    assert all(case.postcondition.evidence for case in cases)
    assert all(case.postcondition.assertions for case in cases)
    assert len({case.fixture.fixture_id for case in cases}) == 60
    assert len({case.verifier for case in cases}) == 60


def test_plan_prints_exactly_180_requests_without_attempts() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/live_eval_plan.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    requests = [json.loads(line) for line in completed.stdout.splitlines()]

    assert len(requests) == 180
    assert {request["repetition"] for request in requests} == {1, 2, 3}
    assert all(request["schema"] == "zebra.live-eval-request.v1" for request in requests)
    assert not (ROOT / "evals" / "live" / "attempts.jsonl").exists()


def test_every_live_eval_case_has_an_executable_fixture(tmp_path: Path) -> None:
    for case in load_live_eval_cases(CASES_PATH):
        workspace = tmp_path / case.case_id
        workspace.mkdir()
        materialize(
            {"case_id": case.case_id, "fixture": {"fixture_id": case.fixture.fixture_id}},
            workspace,
        )
        assert (workspace / "fixture-manifest.json").is_file()


def test_memory_verifier_classifies_malformed_output_as_failure(tmp_path: Path) -> None:
    (tmp_path / "memory-result.json").write_text('{"selected_scope":"user-7"')
    checks = _verify_case(
        "memory_recovery",
        tmp_path,
        "claimed success",
        {"required_terms": ["user-7"], "validation": ["memory-result.json"]},
    )

    assert checks == [False, False, False]


def test_incomplete_report_withholds_all_rates() -> None:
    cases = (_case("one"), _case("two"))
    report = build_live_eval_report(cases, (_attempt(cases[0], 1, passed=True),))

    assert report.complete is False
    assert report.attempt_count == 1
    assert report.expected_attempt_count == 6
    assert report.missing_attempts == ("one#2", "one#3", "two#1", "two#2", "two#3")
    assert report.first_success_rate is None
    assert report.final_success_rate is None
    assert report.human_intervention_rate is None
    assert report.false_completion_rate is None
    assert report.recovery_success_rate is None
    assert report.citation_support_rate is None
    assert report.average_repeated_tool_calls is None
    assert report.average_first_public_feedback_ms is None
    assert report.average_total_duration_ms is None
    assert report.cost_per_successful_task_usd is None


def test_runner_failures_are_reported_without_claiming_human_intervention(
    tmp_path: Path,
) -> None:
    failures = tmp_path / "attempts.failures.jsonl"
    failures.write_text(
        "\n".join(
            (
                json.dumps({"case_id": "one", "repetition": 1}),
                json.dumps({"case_id": "one", "repetition": 1}),
                json.dumps({"case_id": "two", "repetition": 2}),
            )
        ),
        encoding="utf-8",
    )

    assert _runner_failure_summary(failures) == {
        "runner_process_failure_count": 3,
        "runner_recovered_attempt_count": 2,
    }


def test_efficiency_metrics_use_durable_execution_boundaries(tmp_path: Path) -> None:
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import new_session_id
    from agent_storage import SQLiteEventStore

    session_id = new_session_id()
    store = SQLiteEventStore(tmp_path / "session.sqlite")
    for sequence, event_type, payload in (
        (0, EventType.SESSION_CREATED, {"title": "cache boundary"}),
        (1, EventType.MODEL_RESPONSE_RECEIVED, {"prompt_cache_miss_tokens": 10}),
        (
            2,
            EventType.CONTEXT_COMPACTED,
            {
                "attempt_number": 1,
                "before_tokens": 100,
                "after_tokens": 50,
                "removed_message_count": 2,
                "retained_message_count": 2,
                "within_budget": True,
                "provenance": "test",
            },
        ),
        (3, EventType.MODEL_RESPONSE_RECEIVED, {"prompt_cache_hit_tokens": 8}),
    ):
        store.append(
            SessionEvent.create(
                session_id=session_id,
                sequence=sequence,
                event_type=event_type,
                actor=EventActor.HARNESS,
                payload=payload,
            )
        )

    metrics = _load_model_metrics(
        {"database_path": str(tmp_path / "session.sqlite"), "session_id": str(session_id)}
    )

    assert [item["cache_boundary"] for item in metrics] == ["cold_start", "compaction"]


def test_complete_report_uses_repetition_one_for_first_success() -> None:
    one, two = _case("one"), _case("two")
    attempts = (
        _attempt(one, 2, passed=True, repeated_tool_calls=2, cost_usd=0.3),
        _attempt(two, 3, passed=True, cost_usd=0.2),
        _attempt(one, 1, passed=False, completion_claimed=True, cost_usd=0.1),
        _attempt(two, 1, passed=True, citation_supported=True, cost_usd=0.2),
        _attempt(one, 3, passed=True, recovery_succeeded=True, cost_usd=0.3),
        _attempt(two, 2, passed=True, human_intervention=True, cost_usd=0.2),
    )

    report = build_live_eval_report((one, two), attempts)

    assert report.complete is True
    assert report.first_success_rate == 0.5
    assert report.final_success_rate == 1.0
    assert report.human_intervention_rate == pytest.approx(1 / 6)
    assert report.false_completion_rate == pytest.approx(1 / 6)
    assert report.recovery_success_rate == 1.0
    assert report.citation_support_rate == 1.0
    assert report.average_repeated_tool_calls == pytest.approx(1 / 3)
    assert report.cost_per_successful_task_usd == pytest.approx(0.65)


def test_attempt_loader_rejects_self_reported_evidence_tier(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    path.write_text(
        json.dumps({"case_id": "one", "evidence_tier": "real_model"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema"):
        load_live_eval_attempts(path)


def test_real_model_attempt_requires_zebra_and_provider_receipts() -> None:
    case = _case("one")

    with pytest.raises(ValueError, match="provider model-call ids"):
        _attempt(case, 1, passed=True, model_call_ids=())


def test_real_model_attempt_requires_independent_runtime_attestation() -> None:
    case = _case("one")

    with pytest.raises(ValueError, match="independent runtime attestation"):
        _attempt(case, 1, passed=True, runner_attested=False)


def test_scripted_attempt_is_never_counted_as_real_model() -> None:
    case = _case("one")
    scripted = _attempt(
        case,
        1,
        passed=True,
        runner_kind="scripted",
        provider=None,
        model=None,
        model_call_ids=(),
    )

    report = build_live_eval_report((case,), (scripted,))

    assert scripted.evidence_tier == "scripted"
    assert report.attempt_count == 0
    assert report.complete is False


def test_attempt_loader_rejects_tampered_capture(tmp_path: Path) -> None:
    case = _case("one")
    envelope = _envelope(case)
    envelope["capture"]["total_duration_ms"] = 999  # type: ignore[index]
    path = tmp_path / "attempts.jsonl"
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="capture digest mismatch"):
        load_live_eval_attempts(path)


def test_report_rejects_verifier_contract_mismatch() -> None:
    case = _case("one")
    attempt = _attempt(case, 1, passed=True, verifier="other.verifier")

    with pytest.raises(ValueError, match="verifier mismatch"):
        build_live_eval_report((case,), (attempt,))


def test_report_rejects_unknown_or_duplicate_attempts() -> None:
    case = _case("one")
    with pytest.raises(ValueError, match="unknown live eval case"):
        build_live_eval_report((case,), (_attempt(_case("missing"), 1, passed=True),))
    with pytest.raises(ValueError, match="unique and within"):
        build_live_eval_report(
            (case,),
            (_attempt(case, 1, passed=True), _attempt(case, 1, passed=True)),
        )


def test_report_rejects_reused_real_execution_evidence() -> None:
    case = _case("one")
    first = _attempt(case, 1, passed=True)
    second = _attempt(case, 2, passed=True)

    with pytest.raises(ValueError, match="attempt ids must be unique"):
        build_live_eval_report(
            (case,),
            (first, replace(second, attempt_id=first.attempt_id)),
        )
    with pytest.raises(ValueError, match="model calls cannot be reused"):
        build_live_eval_report(
            (case,),
            (first, replace(second, model_call_ids=first.model_call_ids)),
        )


def test_complete_report_withholds_cost_when_provider_cost_is_missing() -> None:
    case = _case("one")
    attempts = tuple(
        _attempt(case, repetition, passed=True, cost_usd=None) for repetition in range(1, 4)
    )

    report = build_live_eval_report((case,), attempts)

    assert report.complete is True
    assert report.final_success_rate == 1.0
    assert report.cost_per_successful_task_usd is None


def test_executable_runner_keeps_scripted_capture_out_of_real_report(
    tmp_path: Path,
) -> None:
    case = load_live_eval_cases(CASES_PATH)[0]
    attempts_path = tmp_path / "attempts.jsonl"
    runner_output: dict[str, object] = {
        "session_id": None,
        "turn_id": None,
        "model_call_ids": [],
        "attempt_id": "scripted-attempt-1",
        "started_at": "2026-09-26T10:00:00+00:00",
        "finished_at": "2026-09-26T10:00:01+00:00",
        "terminal_outcome": "completed",
        "completion_claimed": True,
        "human_intervention": False,
        "repeated_tool_calls": 0,
        "first_public_feedback_ms": 1,
        "total_duration_ms": 2,
        "cost_usd": None,
    }
    verification_output: dict[str, object] = {
        "verifier": case.verifier,
        "assertions": [
            {
                "assertion": assertion,
                "passed": True,
                "evidence": list(case.postcondition.evidence),
            }
            for assertion in case.postcondition.assertions
        ],
        "runner_attested": False,
        "attestation_evidence": [],
        "citation_supported": None,
        "recovery_succeeded": None,
    }
    runner_config = {
        "schema": "zebra.live-eval-runner-config.v1",
        "kind": "scripted",
        "runner_id": "unit-test-script",
        "runtime": "pytest",
        "provider": None,
        "model": None,
        "argv": [sys.executable, "-c", f"print({json.dumps(json.dumps(runner_output))})"],
    }
    verifier_config = {
        "schema": "zebra.live-eval-verifier-config.v1",
        "kind": "external_postcondition",
        "verifier": case.verifier,
        "argv": [
            sys.executable,
            "-c",
            f"print({json.dumps(json.dumps(verification_output))})",
        ],
    }
    runner_path = tmp_path / "runner.json"
    verifier_path = tmp_path / "verifier.json"
    runner_path.write_text(json.dumps(runner_config), encoding="utf-8")
    verifier_path.write_text(json.dumps(verifier_config), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "scripts/live_eval_run.py",
            "--case-id",
            case.case_id,
            "--repetition",
            "1",
            "--runner-config",
            str(runner_path),
            "--verifier-config",
            str(verifier_path),
            "--attempts",
            str(attempts_path),
        ],
        cwd=ROOT,
        check=True,
    )

    attempts = load_live_eval_attempts(attempts_path)
    report = build_live_eval_report((case,), attempts)
    assert attempts[0].evidence_tier == "scripted"
    assert report.attempt_count == 0
    assert report.complete is False


def _case(case_id: str) -> LiveEvalCase:
    return LiveEvalCase(
        case_id=case_id,
        category="answer",
        split="development",
        title=case_id,
        prompt="Inspect the supplied evidence.",
        fixture=LiveEvalFixture(
            fixture_id=f"{case_id}.v1",
            inputs=(LiveEvalInput("evidence", "bounded fixture"),),
        ),
        postcondition=LiveEvalPostcondition(
            verifier=f"answer.{case_id}.v1",
            evidence=("runner.capture", "answer.evidence"),
            assertions=("goal answered", "facts supported"),
        ),
    )


def _attempt(
    case: LiveEvalCase,
    repetition: int,
    *,
    passed: bool,
    runner_kind: str = "zebra_real_model",
    provider: str | None = "deepseek",
    model: str | None = "deepseek-chat",
    model_call_ids: tuple[str, ...] | None = None,
    verifier: str | None = None,
    completion_claimed: bool = False,
    human_intervention: bool = False,
    repeated_tool_calls: int = 0,
    cost_usd: float | None = 0.0,
    citation_supported: bool | None = None,
    recovery_succeeded: bool | None = None,
    runner_attested: bool = True,
) -> LiveEvalAttempt:
    from typing import cast

    from agent_observability.live_eval_attempts import RunnerKind

    return LiveEvalAttempt(
        case_id=case.case_id,
        repetition=repetition,
        runner_kind=cast(RunnerKind, runner_kind),
        runner_id="runner-1",
        runtime="zebra-cloud-agent",
        provider=provider,
        model=model,
        session_id="session-1",
        turn_id=f"turn-{case.case_id}-{repetition}",
        model_call_ids=(
            (f"call-{case.case_id}-{repetition}",)
            if model_call_ids is None
            else model_call_ids
        ),
        attempt_id=f"attempt-{case.case_id}-{repetition}",
        started_at="2026-09-26T10:00:00+00:00",
        finished_at="2026-09-26T10:00:01+00:00",
        terminal_outcome="completed",
        completion_claimed=completion_claimed,
        human_intervention=human_intervention,
        repeated_tool_calls=repeated_tool_calls,
        first_public_feedback_ms=100,
        total_duration_ms=500,
        cost_usd=cost_usd,
        verifier=verifier or case.verifier,
        assertions=tuple(
            AssertionResult(
                assertion=assertion,
                passed=passed,
                evidence=case.postcondition.evidence,
            )
            for assertion in case.postcondition.assertions
        ),
        runner_attested=runner_attested,
        attestation_evidence=("zebra:model-call:call-1",) if runner_attested else (),
        citation_supported=citation_supported,
        recovery_succeeded=recovery_succeeded,
    )


def _envelope(case: LiveEvalCase) -> dict[str, object]:
    runner = {
        "kind": "zebra_real_model",
        "runner_id": "runner-1",
        "runtime": "zebra-cloud-agent",
        "provider": "deepseek",
        "model": "deepseek-chat",
    }
    capture = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "model_call_ids": ["call-1"],
        "attempt_id": "attempt-one-1",
        "started_at": "2026-09-26T10:00:00+00:00",
        "finished_at": "2026-09-26T10:00:01+00:00",
        "terminal_outcome": "completed",
        "completion_claimed": True,
        "human_intervention": False,
        "repeated_tool_calls": 0,
        "first_public_feedback_ms": 100,
        "total_duration_ms": 500,
        "cost_usd": 0.01,
    }
    verification = {
        "verifier": case.verifier,
        "assertions": [
            {
                "assertion": assertion,
                "passed": True,
                "evidence": list(case.postcondition.evidence),
            }
            for assertion in case.postcondition.assertions
        ],
        "runner_attested": True,
        "attestation_evidence": ["zebra:model-call:call-1"],
        "citation_supported": None,
        "recovery_succeeded": None,
    }
    return {
        "schema": "zebra.live-eval-attempt.v1",
        "case_id": case.case_id,
        "repetition": 1,
        "runner": runner,
        "runner_sha256": digest_json(runner),
        "capture": capture,
        "capture_sha256": digest_json(capture),
        "verification": verification,
        "verification_sha256": digest_json(verification),
    }
