from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

LiveEvalCategory = Literal["answer", "research", "code", "file", "operation", "memory_recovery"]
LiveEvalSplit = Literal["development", "holdout"]


@dataclass(frozen=True)
class LiveEvalInput:
    name: str
    value: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.value.strip():
            raise ValueError("live eval fixture inputs must not be blank")


@dataclass(frozen=True)
class LiveEvalFixture:
    fixture_id: str
    inputs: tuple[LiveEvalInput, ...]

    def __post_init__(self) -> None:
        if not self.fixture_id.strip() or not self.inputs:
            raise ValueError("live eval fixture requires an id and inputs")
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("live eval fixture input names must be unique")


@dataclass(frozen=True)
class LiveEvalPostcondition:
    verifier: str
    evidence: tuple[str, ...]
    assertions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.verifier.strip() or not self.evidence or not self.assertions:
            raise ValueError("live eval postcondition must be explicit")
        if any(not value.strip() for value in (*self.evidence, *self.assertions)):
            raise ValueError("live eval postcondition values must not be blank")
        if len(self.assertions) != len(set(self.assertions)):
            raise ValueError("live eval postcondition assertions must be unique")


@dataclass(frozen=True)
class LiveEvalCase:
    case_id: str
    category: LiveEvalCategory
    split: LiveEvalSplit
    title: str
    prompt: str
    fixture: LiveEvalFixture
    postcondition: LiveEvalPostcondition
    repetitions: int = 3

    def __post_init__(self) -> None:
        for name in ("case_id", "title", "prompt"):
            if not getattr(self, name).strip():
                raise ValueError(f"live eval {name} must not be blank")
        if self.repetitions != 3:
            raise ValueError("live eval cases require exactly three repetitions")

    @property
    def verifier(self) -> str:
        return self.postcondition.verifier


def load_live_eval_cases(path: Path) -> tuple[LiveEvalCase, ...]:
    if not path.is_dir():
        raise ValueError("live eval case path must be a directory")
    values: list[object] = []
    for item in sorted(path.glob("*.json")):
        value = json.loads(item.read_text(encoding="utf-8"))
        values.extend(value if isinstance(value, list) else [value])
    cases = tuple(_case_from_json(value) for value in values)
    if not cases:
        raise ValueError("live eval case directory must include json cases")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("live eval case ids must be unique")
    return cases


def case_to_json(case: LiveEvalCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "split": case.split,
        "title": case.title,
        "prompt": case.prompt,
        "fixture": {
            "fixture_id": case.fixture.fixture_id,
            "inputs": {item.name: item.value for item in case.fixture.inputs},
        },
        "postcondition": {
            "verifier": case.postcondition.verifier,
            "evidence": list(case.postcondition.evidence),
            "assertions": list(case.postcondition.assertions),
        },
        "repetitions": case.repetitions,
    }


def _case_from_json(value: object) -> LiveEvalCase:
    item = _object(value, "case")
    fixture = _object(item.get("fixture"), "fixture")
    raw_inputs = _object(fixture.get("inputs"), "fixture inputs")
    postcondition = _object(item.get("postcondition"), "postcondition")
    return LiveEvalCase(
        case_id=_string(item, "case_id"),
        category=cast(
            LiveEvalCategory,
            _choice(
                item,
                "category",
                {"answer", "research", "code", "file", "operation", "memory_recovery"},
            ),
        ),
        split=cast(LiveEvalSplit, _choice(item, "split", {"development", "holdout"})),
        title=_string(item, "title"),
        prompt=_string(item, "prompt"),
        fixture=LiveEvalFixture(
            fixture_id=_string(fixture, "fixture_id"),
            inputs=tuple(
                LiveEvalInput(name=str(name), value=_non_blank_string(raw))
                for name, raw in sorted(raw_inputs.items(), key=lambda pair: str(pair[0]))
            ),
        ),
        postcondition=LiveEvalPostcondition(
            verifier=_string(postcondition, "verifier"),
            evidence=_string_list(postcondition, "evidence"),
            assertions=_string_list(postcondition, "assertions"),
        ),
        repetitions=_integer(item, "repetitions", default=3),
    )


def _object(value: object, name: str) -> dict[object, object]:
    if not isinstance(value, dict):
        raise ValueError(f"live eval {name} must be an object")
    return value


def _string(value: dict[object, object], key: str) -> str:
    return _non_blank_string(value.get(key), key)


def _non_blank_string(value: object, key: str = "value") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"live eval field {key} must be a non-blank string")
    return value


def _choice(value: dict[object, object], key: str, allowed: set[str]) -> str:
    result = _string(value, key)
    if result not in allowed:
        raise ValueError(f"live eval field {key} is not supported")
    return result


def _integer(value: dict[object, object], key: str, *, default: int) -> int:
    raw = value.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"live eval field {key} must be an integer")
    return raw


def _string_list(value: dict[object, object], key: str) -> tuple[str, ...]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ValueError(f"live eval field {key} must be a list")
    return tuple(_non_blank_string(item, key) for item in raw)
