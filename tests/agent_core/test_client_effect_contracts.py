from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.client_effects import (
    CLIENT_EFFECT_TERMINAL_STATUSES,
    ClientEffectError,
    ClientEffectExpiredError,
    ClientEffectIdempotencyConflict,
    ClientEffectReceipt,
    ClientEffectReceiptConflict,
    ClientEffectRequest,
    ClientEffectRevisionError,
    ClientEffectStatus,
    client_effect_idempotency_key,
    decide_receipt_admission,
    resolve_effect_idempotency,
)
from agent_core.domain.identifiers import (
    new_client_effect_id,
    new_client_session_id,
    new_task_id,
    new_tool_call_id,
)
from agent_core.domain.sessions import SessionStatus
from pydantic import ValidationError

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _request(**overrides) -> ClientEffectRequest:
    payload = {
        "effect_id": new_client_effect_id(),
        "task_id": new_task_id(),
        "run_id": "run-1",
        "client_session_id": new_client_session_id(),
        "tool_call_id": new_tool_call_id(),
        "action_name": "trench.ui.timeline.open",
        "arguments": {"entityId": "ent-9"},
        "action_contract_digest": "a" * 64,
        "client_binding_digest": "b" * 64,
        "fence_hash": "c" * 64,
        "expected_ui_revision": 4,
        "idempotency_key": "client-effect:1:run-1:2",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
    }
    payload.update(overrides)
    return ClientEffectRequest.model_validate(payload)


def _receipt(request: ClientEffectRequest, **overrides) -> ClientEffectReceipt:
    payload = {
        "receipt_id": uuid4(),
        "effect_id": request.effect_id,
        "idempotency_key": request.idempotency_key,
        "request_digest": request.request_digest,
        "status": ClientEffectStatus.SUCCEEDED,
        "result": {"opened": True},
        "received_at": NOW + timedelta(seconds=5),
    }
    payload.update(overrides)
    return ClientEffectReceipt.model_validate(payload)


def test_request_pins_all_digests_revision_and_idempotency() -> None:
    request = _request()
    assert len(request.request_digest) == 64
    assert request.idempotency_key.startswith("client-effect:")
    with pytest.raises(ValueError):
        _request(fence_hash="short")
    with pytest.raises(ValueError):
        _request(expected_ui_revision=-1)


def test_expired_or_stale_effects_fail_closed() -> None:
    expired = _request(status=ClientEffectStatus.PENDING)
    expired = expired.model_copy(
        update={"expires_at": NOW - timedelta(seconds=1)}
    )
    with pytest.raises(ClientEffectExpiredError):
        expired.ensure_receiptable(
            current_ui_revision=expired.expected_ui_revision, now=NOW
        )
    pending = _request()
    with pytest.raises(ClientEffectRevisionError):
        pending.ensure_receiptable(
            current_ui_revision=pending.expected_ui_revision + 3, now=NOW
        )
    resolved = _request(status=ClientEffectStatus.SUCCEEDED)
    with pytest.raises(ClientEffectReceiptConflict):
        resolved.ensure_receiptable(
            current_ui_revision=resolved.expected_ui_revision, now=NOW
        )
    pending.ensure_receiptable(
        current_ui_revision=pending.expected_ui_revision, now=NOW
    )


def test_receipt_rejects_observer_and_secret_results() -> None:
    request = _request()
    for override in (
        {"controller": False},
        {"result": {"sessionToken": "abc"}},
        {"result": {"cookie": "sid=1"}},
    ):
        with pytest.raises(ValidationError) as info:
            _receipt(request, **override)
        causes = [
            error.get("ctx", {}).get("error") for error in info.value.errors()
        ]
        assert any(isinstance(cause, ClientEffectError) for cause in causes)


def test_receipt_only_accepts_terminal_semantic_statuses() -> None:
    request = _request()
    for status in (ClientEffectStatus.PENDING, ClientEffectStatus.UNCERTAIN):
        with pytest.raises(ValidationError) as info:
            _receipt(request, status=status)
        causes = [
            error.get("ctx", {}).get("error") for error in info.value.errors()
        ]
        assert any(
            isinstance(cause, ClientEffectReceiptConflict) for cause in causes
        )
    assert ClientEffectStatus.UNCERTAIN not in CLIENT_EFFECT_TERMINAL_STATUSES


def test_one_effect_accepts_one_semantically_consistent_receipt() -> None:
    request = _request()
    first = _receipt(request)
    assert decide_receipt_admission(request, None, first) == "accept"
    assert decide_receipt_admission(request, first, first) == "replay"
    conflicting = _receipt(request, status=ClientEffectStatus.FAILED)
    assert decide_receipt_admission(request, first, conflicting) == "conflict"


def test_idempotency_replay_and_conflict() -> None:
    request = _request()
    assert resolve_effect_idempotency(
        idempotency_key=request.idempotency_key,
        request_digest=request.request_digest,
        existing=None,
    ) == "schedule"
    assert resolve_effect_idempotency(
        idempotency_key=request.idempotency_key,
        request_digest=request.request_digest,
        existing=request,
    ) == "replay"
    with pytest.raises(ClientEffectIdempotencyConflict):
        resolve_effect_idempotency(
            idempotency_key=request.idempotency_key,
            request_digest="d" * 64,
            existing=request,
        )


def test_idempotency_key_is_derived_from_the_tool_identity() -> None:
    task_id = new_task_id()
    tool_call_id = new_tool_call_id()
    assert client_effect_idempotency_key(
        task_id=task_id, run_id="run-1", tool_call_id=tool_call_id
    ) == f"client-effect:{task_id}:run-1:{tool_call_id}"


def test_session_supports_the_waiting_client_effect_lifecycle() -> None:
    from agent_core.domain.sessions import Session

    session = Session.create(title="client effect lifecycle", created_at=NOW)
    running = session.transition_to(SessionStatus.READY).transition_to(
        SessionStatus.RUNNING
    )
    waiting = running.transition_to(SessionStatus.WAITING_CLIENT_EFFECT)
    resumed = waiting.transition_to(SessionStatus.READY)
    assert resumed.status is SessionStatus.READY
    with pytest.raises(ValueError):
        waiting.transition_to(SessionStatus.RUNNING)
