"""Real database recovery from the browser receipt / command contract regression."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from agent_core.contracts.session_commands import SessionCommand, validate_accepted_session_command
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage.postgres.client_effect_recovery import ClientEffectRecovery
from psycopg.types.json import Jsonb

from tests.agent_storage.test_postgres_client_effects import (
    _continuation,
    _receipt,
    _request,
    _with_active_lease,
)
from tests.agent_storage.test_postgres_client_effects import (
    pytestmark as _postgres_mark,
)
from tests.agent_storage.test_postgres_client_effects import stores as _stores_fixture

pytestmark = _postgres_mark
stores = _stores_fixture


def _seed(stores, *, expired=False):
    dispatch, _, _, events, dsn, namespace = stores
    request = _with_active_lease(stores, _request())
    dispatch.schedule(
        request, continuation=_continuation(request), session_id=request.parent_session_id
    )
    events.append(
        SessionEvent.create(
            session_id=request.parent_session_id,
            sequence=1,
            event_type=EventType.SESSION_WAITING_FOR_CLIENT_EFFECT,
            actor=EventActor.HARNESS,
            payload={
                "reason": "waiting_client_effect",
                "client_effect_ids": [str(request.effect_id)],
                "metadata": {},
            },
            created_at=datetime.now(UTC),
        )
    )
    recovery = ClientEffectRecovery(dsn, deployment_namespace=namespace)
    if expired:
        with recovery._database.connect() as connection:
            connection.execute(
                "UPDATE client_effects SET requested_at=%s, expires_at=%s WHERE effect_id=%s",
                (
                    datetime.now(UTC) - timedelta(minutes=2),
                    datetime.now(UTC) - timedelta(minutes=1),
                    request.effect_id,
                ),
            )
    return request, recovery


def _recover(recovery, request, *, dry_run=False):
    with recovery._database.connect() as connection:
        return recovery._recover(connection, request.parent_session_id, dry_run)


def test_expired_wait_resumes_once_with_failed_observation(stores):
    request, recovery = _seed(stores, expired=True)
    assert _recover(recovery, request, dry_run=True) == 1
    assert _recover(recovery, request) == 1
    assert _recover(recovery, request) == 0
    event = stores[3].list_for_session(request.parent_session_id)[-1]
    command = validate_accepted_session_command(
        event.payload,
        session_id=request.parent_session_id,
        idempotency_key=event.idempotency_key,
    )
    assert command.payload["client_effect_result"]["status"] == "expired"


@pytest.mark.parametrize("kind", ["cancel", "stop", "suspend"])
def test_pending_control_prevents_recovery(stores, kind):
    request, recovery = _seed(stores, expired=True)
    command = SessionCommand(
        session_id=request.parent_session_id,
        kind=kind,
        expected_revision=1,
        idempotency_key=f"control-{kind}",
    )
    stores[3].append(
        SessionEvent.create(
            session_id=request.parent_session_id,
            sequence=2,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
            idempotency_key=command.idempotency_key,
        )
    )
    assert _recover(recovery, request) == 0


@pytest.mark.parametrize("cancelled", [False, True])
def test_legacy_receipt_repair_preserves_old_event_and_does_not_revive_cancelled(stores, cancelled):
    request, recovery = _seed(stores)
    result = {
        "client_effect_id": str(request.effect_id),
        "tool_call_id": str(request.tool_call_id),
        "action_name": request.action_name,
        "status": "succeeded",
        "result": {"offered": True},
    }
    command = SessionCommand(
        session_id=request.parent_session_id,
        kind="resume",
        expected_revision=1,
        idempotency_key=f"client-effect-resume:{request.effect_id}",
        payload={"client_effect_result": result},
    )
    legacy = command.event_payload()
    legacy["fingerprint"] = sha256(
        f"{request.parent_session_id}:client-effect:{request.effect_id}".encode()
    ).hexdigest()
    original = SessionEvent.create(
        session_id=request.parent_session_id,
        sequence=2,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.HARNESS,
        payload=legacy,
        created_at=datetime.now(UTC),
        idempotency_key=command.idempotency_key,
    )
    stores[3].append(original)
    with recovery._database.connect() as connection:
        connection.execute(
            """INSERT INTO client_effect_receipts VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                stores[5],
                request.effect_id,
                command.command_id,
                request.idempotency_key,
                request.request_digest,
                "succeeded",
                Jsonb({"offered": True}),
                datetime.now(UTC),
            ),
        )
    if cancelled:
        stores[3].append(
            SessionEvent.create(
                session_id=request.parent_session_id,
                sequence=3,
                event_type=EventType.SESSION_CANCELLED,
                actor=EventActor.HARNESS,
                payload={"reason": "cancelled"},
                created_at=datetime.now(UTC),
            )
        )
    assert _recover(recovery, request) == (0 if cancelled else 1)
    assert _recover(recovery, request) == 0
    events = stores[3].list_for_session(request.parent_session_id)
    assert events[2] == original
    if not cancelled:
        validate_accepted_session_command(
            events[-1].payload,
            session_id=request.parent_session_id,
            idempotency_key=events[-1].idempotency_key,
        )


@pytest.mark.parametrize("boundary", [EventType.SESSION_SUSPENDED, EventType.TURN_COMPLETED,
    EventType.TURN_FAILED, EventType.TURN_CANCELLED])
def test_stale_wait_candidate_cannot_cross_new_boundary(stores, boundary):
    request, recovery = _seed(stores, expired=True)
    # A maintenance candidate was selected before the pause/close committed.
    marker = SessionEvent.create(session_id=request.parent_session_id, sequence=2,
        event_type=EventType.SESSION_SUSPENDED, actor=EventActor.HARNESS,
        payload={"reason": "execution_storage_contention", "metadata": {"retryable": False}})
    stores[3].append(marker.model_copy(update={"event_type": boundary}))
    before = stores[3].list_for_session(request.parent_session_id)
    assert _recover(recovery, request) == 0
    assert stores[3].list_for_session(request.parent_session_id) == before


def test_real_late_receipt_is_retained_but_cannot_resume_paused_worker(stores):
    from uuid import uuid4

    from agent_core.domain.client_sessions import ClientSession, ClientSessionGrant
    from zebra_agent_worker.client_effect_continuation import has_trusted_client_effect_resume
    from zebra_agent_worker.client_effect_resume import recover_client_effect_wakeup

    request, _ = _seed(stores)
    stores[2].create_session(ClientSession(
        session_id=request.client_session_id,
        grant=ClientSessionGrant(grant_id=uuid4(), host_app_id="fixture-host",
            namespace_id="tenant-1", frontend_app_id="fixture-web",
            origin="https://app.fixture.example", user_ref="user-1", profile_digest="a" * 64,
            scopes=("client.action",), expires_at=datetime.now(UTC) + timedelta(hours=1)),
        credential_hash="d" * 64, created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1), ui_revision=request.expected_ui_revision,
    ))
    stores[3].append(SessionEvent.create(session_id=request.parent_session_id, sequence=2,
        event_type=EventType.SESSION_SUSPENDED, actor=EventActor.HARNESS,
        payload={"reason": "execution_storage_contention", "metadata": {"retryable": False}}))
    receipt = _receipt(request)
    accepted = stores[1].accept_receipt(receipt, request_fence_hash=request.fence_hash,
        session_id=request.parent_session_id)
    assert not accepted.replayed
    before = stores[3].list_for_session(request.parent_session_id)
    assert not has_trusted_client_effect_resume(before)
    assert recover_client_effect_wakeup(before) is None
    duplicate = stores[1].accept_receipt(receipt, request_fence_hash=request.fence_hash,
        session_id=request.parent_session_id)
    assert duplicate.replayed
    assert stores[3].list_for_session(request.parent_session_id) == before
    assert stores[1].read_receipt(request.effect_id) == receipt
