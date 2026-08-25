from datetime import UTC, datetime

import pytest
from agent_core.domain.client_run_bindings import (
    ClientBindingNarrowingError,
    ClientRunBinding,
    client_run_binding_key,
)
from agent_core.domain.identifiers import (
    new_client_run_binding_id,
    new_client_session_id,
    new_task_id,
)
from pydantic import ValidationError

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def _binding(**overrides) -> ClientRunBinding:
    payload = {
        "binding_id": new_client_run_binding_id(),
        "task_id": new_task_id(),
        "run_id": "run-1",
        "client_session_id": new_client_session_id(),
        "profile_digest": "a" * 64,
        "mounted_snapshot_digest": "b" * 64,
        "task_capability_scope": (
            "trench.ui.event.open",
            "trench.ui.entity.select",
        ),
        "allowed_actions": ("trench.ui.event.open",),
        "binding_revision": 1,
        "created_at": NOW,
    }
    payload.update(overrides)
    return ClientRunBinding.model_validate(payload)


def test_binding_key_pins_task_run_and_session() -> None:
    task_id = new_task_id()
    session_id = new_client_session_id()
    binding = _binding(task_id=task_id, run_id="run-9", client_session_id=session_id)
    assert client_run_binding_key(task_id, "run-9", session_id) == (
        f"{task_id}:run-9:{session_id}"
    )
    assert binding.run_id == "run-9"


def test_allowed_actions_must_narrow_the_task_capability_scope() -> None:
    with pytest.raises(ValidationError) as info:
        _binding(allowed_actions=("trench.ui.report.publish",))
    causes = [error.get("ctx", {}).get("error") for error in info.value.errors()]
    assert any(isinstance(cause, ClientBindingNarrowingError) for cause in causes)


def test_narrowing_only_shrinks_and_bumps_the_revision() -> None:
    binding = _binding()
    narrowed = binding.narrow(
        mounted_actions=("trench.ui.entity.select",),
        revision_reason="route change",
    )
    assert narrowed.allowed_actions == ()
    assert narrowed.binding_revision == binding.binding_revision + 1
    still_wide = _binding(
        allowed_actions=("trench.ui.event.open", "trench.ui.entity.select")
    )
    assert still_wide.binding_digest != _binding().binding_digest


def test_binding_digest_is_stable_and_revision_free() -> None:
    first = _binding()
    reissued = first.model_copy(update={"binding_revision": 7, "created_at": NOW})
    assert first.binding_digest == reissued.binding_digest


def test_binding_pins_profile_and_mounted_digests() -> None:
    with pytest.raises(ValueError):
        _binding(profile_digest="not-a-digest")
    with pytest.raises(ValueError):
        _binding(mounted_snapshot_digest="short")
