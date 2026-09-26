from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from agent_observability.live_eval_cases import LiveEvalCase

RunnerKind = Literal["zebra_real_model", "real_dependency", "scripted"]
AttemptEvidenceTier = Literal["real_model", "real_dependency", "scripted"]
TerminalOutcome = Literal["completed", "partial", "blocked", "failed", "cancelled"]


@dataclass(frozen=True)
class AssertionResult:
    assertion: str
    passed: bool
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.assertion.strip() or not self.evidence:
            raise ValueError("live eval assertion requires a name and evidence")
        if any(not item.strip() for item in self.evidence):
            raise ValueError("live eval assertion evidence must not be blank")


@dataclass(frozen=True)
class LiveEvalAttempt:
    case_id: str
    repetition: int
    runner_kind: RunnerKind
    runner_id: str
    runtime: str
    provider: str | None
    model: str | None
    session_id: str | None
    turn_id: str | None
    model_call_ids: tuple[str, ...]
    attempt_id: str
    started_at: str
    finished_at: str
    terminal_outcome: TerminalOutcome
    completion_claimed: bool
    human_intervention: bool
    repeated_tool_calls: int
    first_public_feedback_ms: int
    total_duration_ms: int
    cost_usd: float | None
    verifier: str
    assertions: tuple[AssertionResult, ...]
    runner_attested: bool
    attestation_evidence: tuple[str, ...]
    citation_supported: bool | None = None
    recovery_succeeded: bool | None = None

    def __post_init__(self) -> None:
        for name in (
            "case_id",
            "runner_id",
            "runtime",
            "attempt_id",
            "terminal_outcome",
            "verifier",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"live eval attempt {name} must not be blank")
        if self.repetition < 1:
            raise ValueError("live eval repetition must be positive")
        for name in ("repeated_tool_calls", "first_public_feedback_ms", "total_duration_ms"):
            if getattr(self, name) < 0:
                raise ValueError(f"live eval {name} must not be negative")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("live eval cost_usd must not be negative")
        if self.first_public_feedback_ms > self.total_duration_ms:
            raise ValueError("first public feedback cannot exceed total duration")
        started = _timestamp(self.started_at)
        finished = _timestamp(self.finished_at)
        if finished < started:
            raise ValueError("live eval attempt cannot finish before it starts")
        if not self.assertions:
            raise ValueError("live eval attempt requires verifier assertions")
        if self.runner_kind == "zebra_real_model":
            required = (self.provider, self.model, self.session_id, self.turn_id)
            if any(value is None or not value.strip() for value in required):
                raise ValueError("real-model attempts require provider and Zebra runtime ids")
            if not self.model_call_ids:
                raise ValueError("real-model attempts require provider model-call ids")
            if not self.runner_attested or not self.attestation_evidence:
                raise ValueError("real-model attempts require independent runtime attestation")
        if self.runner_kind == "scripted" and (
            self.provider is not None or self.model is not None or self.model_call_ids
        ):
            raise ValueError("scripted runners cannot claim provider model evidence")

    @property
    def evidence_tier(self) -> AttemptEvidenceTier:
        if self.runner_kind == "zebra_real_model":
            return "real_model"
        return self.runner_kind

    @property
    def postcondition_passed(self) -> bool:
        return all(item.passed for item in self.assertions)

    @property
    def succeeded(self) -> bool:
        return self.terminal_outcome == "completed" and self.postcondition_passed

    @property
    def false_completion(self) -> bool:
        return self.completion_claimed and not self.postcondition_passed

    def validate_case_contract(self, case: LiveEvalCase) -> None:
        if self.verifier != case.postcondition.verifier:
            raise ValueError(f"live eval verifier mismatch for {case.case_id}")
        actual = tuple(item.assertion for item in self.assertions)
        if actual != case.postcondition.assertions:
            raise ValueError(f"live eval assertion contract mismatch for {case.case_id}")
        evidence = {ref for result in self.assertions for ref in result.evidence}
        missing = set(case.postcondition.evidence) - evidence
        if missing:
            raise ValueError(f"live eval evidence contract incomplete for {case.case_id}")


def load_live_eval_attempts(path: Path) -> tuple[LiveEvalAttempt, ...]:
    if not path.is_file():
        raise ValueError("live eval attempts path must be a file")
    attempts = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            attempts.append(attempt_from_envelope(json.loads(line)))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid live eval attempt at line {line_number}: {exc}") from exc
    return tuple(attempts)


def attempt_from_envelope(value: object) -> LiveEvalAttempt:
    envelope = _object(value, "attempt")
    if _string(envelope, "schema") != "zebra.live-eval-attempt.v1":
        raise ValueError("unsupported live eval attempt schema")
    runner = _verified_part(envelope, "runner", "runner_sha256")
    capture = _verified_part(envelope, "capture", "capture_sha256")
    verification = _verified_part(envelope, "verification", "verification_sha256")
    assertions = tuple(
        _assertion_from_json(item)
        for item in _list(verification, "assertions")
    )
    return LiveEvalAttempt(
        case_id=_string(envelope, "case_id"),
        repetition=_integer(envelope, "repetition"),
        runner_kind=cast(
            RunnerKind,
            _choice(runner, "kind", {"zebra_real_model", "real_dependency", "scripted"}),
        ),
        runner_id=_string(runner, "runner_id"),
        runtime=_string(runner, "runtime"),
        provider=_optional_string(runner, "provider"),
        model=_optional_string(runner, "model"),
        session_id=_optional_string(capture, "session_id"),
        turn_id=_optional_string(capture, "turn_id"),
        model_call_ids=_string_tuple(capture, "model_call_ids"),
        attempt_id=_string(capture, "attempt_id"),
        started_at=_string(capture, "started_at"),
        finished_at=_string(capture, "finished_at"),
        terminal_outcome=cast(
            TerminalOutcome,
            _choice(
                capture,
                "terminal_outcome",
                {"completed", "partial", "blocked", "failed", "cancelled"},
            ),
        ),
        completion_claimed=_boolean(capture, "completion_claimed"),
        human_intervention=_boolean(capture, "human_intervention"),
        repeated_tool_calls=_integer(capture, "repeated_tool_calls"),
        first_public_feedback_ms=_integer(capture, "first_public_feedback_ms"),
        total_duration_ms=_integer(capture, "total_duration_ms"),
        cost_usd=_optional_number(capture, "cost_usd"),
        verifier=_string(verification, "verifier"),
        assertions=assertions,
        runner_attested=_boolean(verification, "runner_attested"),
        attestation_evidence=_string_tuple(verification, "attestation_evidence"),
        citation_supported=_optional_boolean(verification, "citation_supported"),
        recovery_succeeded=_optional_boolean(verification, "recovery_succeeded"),
    )


def digest_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        normalized = value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("live eval timestamps must use ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("live eval timestamps must include a timezone")
    return parsed


def _verified_part(
    envelope: dict[object, object], key: str, digest_key: str
) -> dict[object, object]:
    value = _object(envelope.get(key), key)
    if _string(envelope, digest_key) != digest_json(value):
        raise ValueError(f"live eval {key} digest mismatch")
    return value


def _assertion_from_json(value: object) -> AssertionResult:
    item = _object(value, "assertion")
    return AssertionResult(
        assertion=_string(item, "assertion"),
        passed=_boolean(item, "passed"),
        evidence=_string_tuple(item, "evidence"),
    )


def _object(value: object, name: str) -> dict[object, object]:
    if not isinstance(value, dict):
        raise ValueError(f"live eval {name} must be an object")
    return value


def _list(value: dict[object, object], key: str) -> list[object]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ValueError(f"live eval field {key} must be a list")
    return raw


def _string(value: dict[object, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"live eval field {key} must be a non-blank string")
    return raw


def _optional_string(value: dict[object, object], key: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"live eval field {key} must be a non-blank string or null")
    return raw


def _choice(value: dict[object, object], key: str, allowed: set[str]) -> str:
    result = _string(value, key)
    if result not in allowed:
        raise ValueError(f"live eval field {key} is not supported")
    return result


def _integer(value: dict[object, object], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"live eval field {key} must be an integer")
    return raw


def _boolean(value: dict[object, object], key: str) -> bool:
    raw = value.get(key)
    if not isinstance(raw, bool):
        raise ValueError(f"live eval field {key} must be a boolean")
    return raw


def _optional_boolean(value: dict[object, object], key: str) -> bool | None:
    raw = value.get(key)
    if raw is not None and not isinstance(raw, bool):
        raise ValueError(f"live eval field {key} must be a boolean or null")
    return raw


def _optional_number(value: dict[object, object], key: str) -> float | None:
    raw = value.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"live eval field {key} must be a number or null")
    return float(raw)


def _string_tuple(value: dict[object, object], key: str) -> tuple[str, ...]:
    return tuple(_string({"value": item}, "value") for item in _list(value, key))
