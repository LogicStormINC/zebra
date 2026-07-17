from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from agent_observability.replay import ReplayResult

EvalCategory = Literal[
    "bugfix",
    "refactor",
    "security",
    "recovery",
    "analysis",
    "provider",
]


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: EvalCategory
    title: str
    prompt: str
    min_events: int = 1
    min_tool_results: int = 0
    max_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("eval case_id must not be blank")
        if not self.title.strip():
            raise ValueError("eval title must not be blank")
        if not self.prompt.strip():
            raise ValueError("eval prompt must not be blank")
        if self.min_events < 1:
            raise ValueError("eval min_events must be at least 1")
        if self.min_tool_results < 0:
            raise ValueError("eval min_tool_results must not be negative")
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise ValueError("eval max_cost_usd must not be negative")


@dataclass(frozen=True)
class EvalGrade:
    case_id: str
    passed: bool
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvalRunResult:
    grades: tuple[EvalGrade, ...]

    @property
    def passed(self) -> bool:
        return all(grade.passed for grade in self.grades)

    @property
    def pass_count(self) -> int:
        return sum(1 for grade in self.grades if grade.passed)

    @property
    def total_count(self) -> int:
        return len(self.grades)

    @property
    def average_score(self) -> float:
        if not self.grades:
            return 0.0
        return sum(grade.score for grade in self.grades) / len(self.grades)


@dataclass(frozen=True)
class ReleaseGatePolicy:
    min_pass_rate: float = 1.0
    min_average_score: float = 1.0

    def __post_init__(self) -> None:
        if not 0 <= self.min_pass_rate <= 1:
            raise ValueError("release gate min_pass_rate must be between 0 and 1")
        if not 0 <= self.min_average_score <= 1:
            raise ValueError("release gate min_average_score must be between 0 and 1")


@dataclass(frozen=True)
class ReleaseGateResult:
    passed: bool
    pass_rate: float
    average_score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class LocalEvalGrader:
    def grade(self, case: EvalCase, replay: ReplayResult) -> EvalGrade:
        reasons: list[str] = []
        if replay.event_count < case.min_events:
            reasons.append("event count below case minimum")
        if replay.tool_result_count < case.min_tool_results:
            reasons.append("tool result count below case minimum")
        if case.max_cost_usd is not None and replay.cost_usd > case.max_cost_usd:
            reasons.append("cost exceeds case maximum")
        passed = not reasons
        return EvalGrade(
            case_id=case.case_id,
            passed=passed,
            score=1.0 if passed else 0.0,
            reasons=tuple(reasons),
        )


@dataclass(frozen=True)
class LocalEvalRunner:
    grader: LocalEvalGrader = LocalEvalGrader()

    def run(
        self,
        cases: tuple[EvalCase, ...],
        replays: tuple[ReplayResult, ...],
    ) -> EvalRunResult:
        if not cases:
            raise ValueError("eval run requires at least one case")
        grades: list[EvalGrade] = []
        for index, case in enumerate(cases):
            if index >= len(replays):
                grades.append(
                    EvalGrade(
                        case_id=case.case_id,
                        passed=False,
                        score=0.0,
                        reasons=("missing replay result for eval case",),
                    )
                )
                continue
            grades.append(self.grader.grade(case, replays[index]))
        return EvalRunResult(grades=tuple(grades))


@dataclass(frozen=True)
class LocalReleaseGate:
    policy: ReleaseGatePolicy = ReleaseGatePolicy()

    def evaluate(self, result: EvalRunResult) -> ReleaseGateResult:
        if result.total_count == 0:
            return ReleaseGateResult(
                passed=False,
                pass_rate=0.0,
                average_score=0.0,
                reasons=("release gate requires at least one eval result",),
            )
        pass_rate = result.pass_count / result.total_count
        reasons: list[str] = []
        if pass_rate < self.policy.min_pass_rate:
            reasons.append("eval pass rate below release gate minimum")
        if result.average_score < self.policy.min_average_score:
            reasons.append("eval average score below release gate minimum")
        return ReleaseGateResult(
            passed=not reasons,
            pass_rate=pass_rate,
            average_score=result.average_score,
            reasons=tuple(reasons),
        )


def load_eval_cases(path: Path) -> tuple[EvalCase, ...]:
    if not path.exists():
        raise ValueError("eval case path does not exist")
    if path.is_file():
        return (_case_from_json(json.loads(path.read_text(encoding="utf-8"))),)
    if not path.is_dir():
        raise ValueError("eval case path must be a file or directory")
    cases = [
        _case_from_json(json.loads(case_path.read_text(encoding="utf-8")))
        for case_path in sorted(path.glob("*.json"))
    ]
    if not cases:
        raise ValueError("eval case directory must include at least one json case")
    return tuple(cases)


def _case_from_json(value: object) -> EvalCase:
    if not isinstance(value, dict):
        raise ValueError("eval case json must be an object")
    return EvalCase(
        case_id=_read_str(value, "case_id"),
        category=_read_category(value, "category"),
        title=_read_str(value, "title"),
        prompt=_read_str(value, "prompt"),
        min_events=_read_int(value, "min_events", default=1),
        min_tool_results=_read_int(value, "min_tool_results", default=0),
        max_cost_usd=_read_optional_float(value, "max_cost_usd"),
    )


def _read_str(value: dict[object, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str):
        raise ValueError(f"eval case field {key} must be a string")
    return raw


def _read_category(value: dict[object, object], key: str) -> EvalCategory:
    raw = _read_str(value, key)
    if raw not in {
        "bugfix",
        "refactor",
        "security",
        "recovery",
        "analysis",
        "provider",
    }:
        raise ValueError("eval case category is not supported")
    return cast(EvalCategory, raw)


def _read_int(value: dict[object, object], key: str, *, default: int) -> int:
    raw = value.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"eval case field {key} must be an integer")
    return raw


def _read_optional_float(value: dict[object, object], key: str) -> float | None:
    raw = value.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"eval case field {key} must be a number")
    return float(raw)
