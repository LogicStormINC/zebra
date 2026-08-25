"""Client state context injection acceptance (ADR-CLIENT-01 Gate 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_context.adapter import LocalContextCompiler
from agent_context.client_state import (
    client_state_context_item,
    client_state_evidence,
)
from agent_core.domain.client_context import (
    ClientStateError,
    ClientStateSnapshot,
    sanitize_client_state,
    validate_client_state_snapshot,
)


def _snapshot(**overrides) -> ClientStateSnapshot:
    payload = {
        "client_session_id": "session-1",
        "frontend_app_id": "fixture-web",
        "profile_digest": "a" * 64,
        "ui_revision": 3,
        "state": {"route": "/events/42", "selectedEventId": "evt-9"},
    }
    payload.update(overrides)
    return ClientStateSnapshot.model_validate(payload)


def test_snapshot_digest_is_stable_and_size_bounded() -> None:
    first = _snapshot()
    assert first.state_digest == _snapshot().state_digest
    assert first.state_bytes > 0
    validate_client_state_snapshot(first)


def test_sensitive_keys_are_redacted_and_rejected() -> None:
    sanitized, redacted = sanitize_client_state(
        {"route": "/x", "authToken": "abc", "nested": {"cookie": "sid"}}
    )
    assert sanitized["authToken"] == "__redacted__"
    assert sanitized["nested"]["cookie"] == "__redacted__"
    assert set(redacted) == {"authToken", "nested.cookie"}
    with pytest.raises(ClientStateError):
        validate_client_state_snapshot(_snapshot(state={"sessionToken": "raw"}))


def test_context_item_is_bounded_and_untrusted() -> None:
    item = client_state_context_item(_snapshot())
    assert item.kind.value == "client_state"
    assert item.trust_level.value == "untrusted" or item.trust_level.value == "user"
    assert item.metadata["ui_revision"] == 3
    assert item.metadata["profile_digest"] == "a" * 64
    assert "evt-9" in item.content
    huge = _snapshot(state={"blob": "x" * 70_000})
    with pytest.raises(ClientStateError):
        client_state_context_item(huge)


def test_evidence_round_trips_through_the_compiler() -> None:
    evidence = client_state_evidence(_snapshot(redacted_keys=("authToken",)))
    assert evidence.kind == "client_state"
    compiler = LocalContextCompiler()
    prompt = compiler.build_system_prompt(
        task_input="Analyze the current event",
        workspace_root=Path.cwd(),
        max_tokens=2_000,
        runtime_evidence=(evidence,),
    )
    assert "evt-9" in prompt
    assert "authToken" in prompt


def test_task_runs_without_client_state() -> None:
    compiler = LocalContextCompiler()
    prompt = compiler.build_system_prompt(
        task_input="No client binding",
        workspace_root=Path.cwd(),
        max_tokens=2_000,
        runtime_evidence=(),
    )
    assert "client_state" not in prompt or "Mounted client state" not in prompt
