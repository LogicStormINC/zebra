import pytest
from agent_core.contracts.events import TaskPreparedPayload
from agent_core.domain.skills import MAX_SKILL_COMPONENTS, normalize_skill_components
from pydantic import ValidationError


def test_normalize_skill_components_canonical_unique_bounded_and_sorted() -> None:
    assert normalize_skill_components(["evidence", "Review"]) == ("Review", "evidence")
    with pytest.raises(ValueError):
        normalize_skill_components(["evidence", "evidence"])
    with pytest.raises(ValueError):
        normalize_skill_components([f"skill-{i}" for i in range(MAX_SKILL_COMPONENTS + 1)])


def test_normalize_skill_components_rejects_non_canonical_names() -> None:
    for invalid in ("1leading-digit", "has space", "slash/name", "", "unicode-é"):
        with pytest.raises(ValueError):
            normalize_skill_components((invalid,))


def test_task_prepared_payload_skill_components_is_optional() -> None:
    payload = TaskPreparedPayload(title="title", user_input="user input")
    assert payload.skill_components is None


def test_task_prepared_payload_normalizes_skill_components() -> None:
    payload = TaskPreparedPayload(
        title="title",
        user_input="user input",
        skill_components=["evidence", "Review"],
    )
    assert payload.skill_components == ["Review", "evidence"]


def test_task_prepared_payload_rejects_invalid_skill_components() -> None:
    with pytest.raises(ValidationError):
        TaskPreparedPayload(
            title="title",
            user_input="user input",
            skill_components=["1leading-digit"],
        )
