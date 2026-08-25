"""Real-PostgreSQL acceptance for durable client effects (v33)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.client_effects import (
    ClientEffectContinuation,
    ClientEffectExpiredError,
    ClientEffectFenceError,
    ClientEffectIdempotencyConflict,
    ClientEffectReceipt,
    ClientEffectReceiptConflict,
    ClientEffectRequest,
    ClientEffectRevisionError,
    ClientEffectStatus,
    client_effect_idempotency_key,
)
from agent_core.domain.client_sessions import (
    ClientSession,
    ClientSessionGrant,
)
from agent_core.domain.identifiers import (
    new_client_effect_id,
    new_client_session_id,
    new_session_id,
    new_task_id,
    new_tool_call_id,
)
from agent_storage.postgres.client_effects import (
    PostgresClientEffectDispatch,
    PostgresClientEffectReceipts,
)
from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.migration_runner import apply_postgres_migrations

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEBRA_TEST_POSTGRES_DSN"),
    reason="set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests",
)


@pytest.fixture()
def stores():
    dsn = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    apply_postgres_migrations(dsn)
    namespace = f"client-effect-{uuid4()}"
    return (
        PostgresClientEffectDispatch(dsn, deployment_namespace=namespace),
        PostgresClientEffectReceipts(dsn, deployment_namespace=namespace),
        PostgresClientSessionRegistry(dsn, deployment_namespace=namespace),
        PostgresEventStore(dsn, deployment_namespace=namespace),
        dsn,
        namespace,
    )


def _request(**overrides) -> ClientEffectRequest:
    payload = {
        "effect_id": new_client_effect_id(),
        "task_id": new_task_id(),
        "run_id": "run-1",
        "client_session_id": new_client_session_id(),
        "tool_call_id": new_tool_call_id(),
        "action_name": "app.ui.item.open",
        "arguments": {"itemId": "item-7"},
        "action_contract_digest": "a" * 64,
        "client_binding_digest": "b" * 64,
        "fence_hash": "c" * 64,
        "expected_ui_revision": 1,
        "idempotency_key": f"client-effect:1:run-1:{uuid4()}",
        "requested_at": datetime.now(UTC),
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
    }
    payload.update(overrides)
    return ClientEffectRequest.model_validate(payload)


def _continuation(request: ClientEffectRequest) -> ClientEffectContinuation:
    return ClientEffectContinuation(
        effect_id=request.effect_id,
        task_id=request.task_id,
        run_id=request.run_id,
        tool_call_id=request.tool_call_id,
        action_name=request.action_name,
        assistant_message="opening item",
        model_calls_used=1,
        tool_calls_executed=0,
        created_at=datetime.now(UTC),
    )


def _receipt(request: ClientEffectRequest, **overrides) -> ClientEffectReceipt:
    payload = {
        "receipt_id": uuid4(),
        "effect_id": request.effect_id,
        "idempotency_key": request.idempotency_key,
        "request_digest": request.request_digest,
        "status": ClientEffectStatus.SUCCEEDED,
        "result": {"opened": True},
        "received_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return ClientEffectReceipt.model_validate(payload)


def test_schedule_is_atomic_and_idempotent(stores) -> None:
    dispatch, _, _, events, _, _ = stores
    session_id = new_session_id()
    request = _request()
    outcome = dispatch.schedule(
        request, continuation=_continuation(request), session_id=session_id
    )
    assert outcome.created is True
    replay = dispatch.schedule(
        request, continuation=_continuation(request), session_id=session_id
    )
    assert replay.created is False
    conflicting = _request(arguments={"itemId": "other"})
    conflicting = conflicting.model_copy(
        update={"idempotency_key": request.idempotency_key}
    )
    with pytest.raises(ClientEffectIdempotencyConflict):
        dispatch.schedule(
            conflicting, continuation=_continuation(conflicting), session_id=session_id
        )
    stored = events.list_for_session(session_id)
    scheduled = [e for e in stored if e.event_type.value == "client_effect_scheduled"]
    assert len(scheduled) == 1
    continuation = dispatch.load_continuation(request.effect_id)
    assert continuation is not None and continuation.action_name == request.action_name


def test_receipt_terminal_and_resume_commit_atomically(stores) -> None:
    dispatch, receipts, sessions, events, _, _ = stores
    session_id = new_session_id()
    request = _request()
    dispatch.schedule(
        request, continuation=_continuation(request), session_id=session_id
    )
    sessions.create_session(
        ClientSession(
            session_id=request.client_session_id,
            grant=ClientSessionGrant(
                grant_id=uuid4(),
                host_app_id="fixture-host",
                namespace_id="tenant-1",
                frontend_app_id="fixture-web",
                origin="https://app.fixture.example",
                user_ref="user-1",
                profile_digest="a" * 64,
                scopes=("client.action",),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            ui_revision=request.expected_ui_revision,
        )
    )
    acceptance = receipts.accept_receipt(
        _receipt(request), request_fence_hash=request.fence_hash, session_id=session_id
    )
    assert acceptance.replayed is False
    assert acceptance.resume_command_id is not None
    # replaying the identical receipt does not duplicate commands
    replay = receipts.accept_receipt(
        _receipt(request), request_fence_hash=request.fence_hash, session_id=session_id
    )
    assert replay.replayed is True
    assert replay.resume_command_id == acceptance.resume_command_id
    stream = events.list_for_session(session_id)
    kinds = [event.event_type.value for event in stream]
    assert kinds.count("client_effect_receipt_accepted") == 1
    assert kinds.count("session_command_accepted") == 1
    with pytest.raises(ClientEffectReceiptConflict):
        receipts.accept_receipt(
            _receipt(request, status=ClientEffectStatus.FAILED),
            request_fence_hash=request.fence_hash,
            session_id=session_id,
        )


def test_stale_fence_and_revision_fail_closed_with_zero_writes(stores) -> None:
    dispatch, receipts, _, events, _, _ = stores
    session_id = new_session_id()
    request = _request()
    dispatch.schedule(
        request, continuation=_continuation(request), session_id=session_id
    )
    with pytest.raises(ClientEffectFenceError):
        receipts.accept_receipt(
            _receipt(request),
            request_fence_hash="d" * 64,
            session_id=session_id,
        )
    # the client session never mounted the expected revision -> stale
    with pytest.raises(ClientEffectRevisionError):
        receipts.accept_receipt(
            _receipt(request),
            request_fence_hash=request.fence_hash,
            session_id=session_id,
        )
    kinds_after_failures = [
        event.event_type.value for event in events.list_for_session(session_id)
    ]
    assert set(kinds_after_failures) == {"client_effect_scheduled"}


def test_expired_effect_rejects_receipts(stores) -> None:
    dispatch, receipts, _, _, _, _ = stores
    session_id = new_session_id()
    request = _request(
        requested_at=datetime.now(UTC) - timedelta(hours=2),
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    dispatch.schedule(
        request, continuation=_continuation(request), session_id=session_id
    )
    with pytest.raises(ClientEffectExpiredError):
        receipts.accept_receipt(
            _receipt(request),
            request_fence_hash=request.fence_hash,
            session_id=session_id,
        )


def test_pending_query_is_bounded_and_delivered_marks(stores) -> None:
    dispatch, _, _, _, _, _ = stores
    session_id = new_client_session_id()
    first = _request(client_session_id=session_id)
    second = _request(client_session_id=session_id)
    host_session = new_session_id()
    for request in (first, second):
        dispatch.schedule(
            request, continuation=_continuation(request), session_id=host_session
        )
    pending = dispatch.list_pending(session_id, limit=1)
    assert len(pending) == 1
    assert all(effect.status is ClientEffectStatus.PENDING for effect in pending)
    dispatch.mark_delivered(first.effect_id)
    assert dispatch.get_effect(first.effect_id) is not None
    assert (
        dispatch.get_effect(first.effect_id).status is ClientEffectStatus.DELIVERED
    )


def test_idempotency_key_is_derived_from_tool_identity() -> None:
    task_id = new_task_id()
    tool_call_id = new_tool_call_id()
    key = client_effect_idempotency_key(
        task_id=task_id, run_id="run-1", tool_call_id=tool_call_id
    )
    assert key == f"client-effect:{task_id}:run-1:{tool_call_id}"
