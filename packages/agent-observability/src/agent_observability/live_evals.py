from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Literal, cast

from agent_observability.live_eval_attempts import (
    LiveEvalAttempt,
    load_live_eval_attempts,
)
from agent_observability.live_eval_cases import LiveEvalCase, load_live_eval_cases

LiveEvidenceTier = Literal["real_dependency", "real_model"]


@dataclass(frozen=True)
class LiveEvalReport:
    evidence_tier: LiveEvidenceTier
    case_count: int
    attempt_count: int
    expected_attempt_count: int
    complete: bool
    missing_attempts: tuple[str, ...]
    first_success_rate: float | None
    final_success_rate: float | None
    human_intervention_rate: float | None
    false_completion_rate: float | None
    recovery_success_rate: float | None
    citation_support_rate: float | None
    average_repeated_tool_calls: float | None
    average_first_public_feedback_ms: float | None
    average_total_duration_ms: float | None
    cost_per_successful_task_usd: float | None


def build_live_eval_report(
    cases: tuple[LiveEvalCase, ...],
    attempts: tuple[LiveEvalAttempt, ...],
    *,
    evidence_tier: LiveEvidenceTier = "real_model",
) -> LiveEvalReport:
    if not cases:
        raise ValueError("live eval report requires cases")
    known = {case.case_id: case for case in cases}
    selected = tuple(item for item in attempts if item.evidence_tier == evidence_tier)
    seen: set[tuple[str, int]] = set()
    attempt_ids: set[str] = set()
    runtime_ids: set[tuple[str | None, str | None]] = set()
    model_call_ids: set[str] = set()
    for item in selected:
        case = known.get(item.case_id)
        if case is None:
            raise ValueError(f"unknown live eval case: {item.case_id}")
        item.validate_case_contract(case)
        key = (item.case_id, item.repetition)
        if item.repetition > case.repetitions or key in seen:
            raise ValueError("live eval repetitions must be unique and within case bounds")
        if item.attempt_id in attempt_ids:
            raise ValueError("live eval attempt ids must be unique")
        runtime_id = (item.session_id, item.turn_id)
        if runtime_id != (None, None) and runtime_id in runtime_ids:
            raise ValueError("live eval runtime attempts must be independent")
        if model_call_ids.intersection(item.model_call_ids):
            raise ValueError("live eval model calls cannot be reused across attempts")
        seen.add(key)
        attempt_ids.add(item.attempt_id)
        if runtime_id != (None, None):
            runtime_ids.add(runtime_id)
        model_call_ids.update(item.model_call_ids)
    missing = tuple(
        f"{case.case_id}#{repetition}"
        for case in cases
        for repetition in range(1, case.repetitions + 1)
        if (case.case_id, repetition) not in seen
    )
    complete = not missing
    metrics = _complete_metrics(cases, selected) if complete else _empty_metrics()
    return LiveEvalReport(
        evidence_tier=evidence_tier,
        case_count=len(cases),
        attempt_count=len(selected),
        expected_attempt_count=sum(case.repetitions for case in cases),
        complete=complete,
        missing_attempts=missing,
        **metrics,
    )


def _complete_metrics(
    cases: tuple[LiveEvalCase, ...], attempts: tuple[LiveEvalAttempt, ...]
) -> dict[str, float | None]:
    by_case = {
        case.case_id: tuple(
            sorted(
                (item for item in attempts if item.case_id == case.case_id),
                key=lambda item: item.repetition,
            )
        )
        for case in cases
    }
    successes = {
        case_id for case_id, items in by_case.items() if any(item.succeeded for item in items)
    }
    recovery = [item.recovery_succeeded for item in attempts if item.recovery_succeeded is not None]
    citations = [
        item.citation_supported
        for item in attempts
        if item.citation_supported is not None
    ]
    return {
        "first_success_rate": sum(items[0].succeeded for items in by_case.values()) / len(cases),
        "final_success_rate": len(successes) / len(cases),
        "human_intervention_rate": sum(item.human_intervention for item in attempts)
        / len(attempts),
        "false_completion_rate": sum(item.false_completion for item in attempts) / len(attempts),
        "recovery_success_rate": _optional_rate(recovery),
        "citation_support_rate": _optional_rate(citations),
        "average_repeated_tool_calls": fmean(item.repeated_tool_calls for item in attempts),
        "average_first_public_feedback_ms": fmean(
            item.first_public_feedback_ms for item in attempts
        ),
        "average_total_duration_ms": fmean(item.total_duration_ms for item in attempts),
        "cost_per_successful_task_usd": (
            sum(cast(float, item.cost_usd) for item in attempts) / len(successes)
            if successes and all(item.cost_usd is not None for item in attempts)
            else None
        ),
    }


def _empty_metrics() -> dict[str, float | None]:
    return dict.fromkeys(
        (
            "first_success_rate",
            "final_success_rate",
            "human_intervention_rate",
            "false_completion_rate",
            "recovery_success_rate",
            "citation_support_rate",
            "average_repeated_tool_calls",
            "average_first_public_feedback_ms",
            "average_total_duration_ms",
            "cost_per_successful_task_usd",
        )
    )


def _optional_rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


__all__ = [
    "LiveEvalAttempt",
    "LiveEvalCase",
    "LiveEvalReport",
    "build_live_eval_report",
    "load_live_eval_attempts",
    "load_live_eval_cases",
]
