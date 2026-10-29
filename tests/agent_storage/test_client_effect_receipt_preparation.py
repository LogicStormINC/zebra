"""Actual PG first-receipt input capture and cold original-operation observation."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.client_preparation import ClientPreparationContext
from agent_core.domain.client_sessions import ClientSession, ClientSessionGrant
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_session_id
from agent_storage.postgres.client_effects import PostgresClientEffectReceipts

from tests.agent_storage.test_postgres_client_effects import (
    _continuation,
    _receipt,
    _request,
    _with_active_lease,
)
from tests.agent_storage.test_postgres_client_effects import (
    stores as _stores,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEBRA_TEST_POSTGRES_DSN"), reason="owned PG required"
)


stores = _stores


def prepared(stores):
    dispatch, receipts, sessions, events, dsn, namespace = stores
    parent = new_session_id()
    effect = _with_active_lease(stores, _request(parent_session_id=parent))
    dispatch.schedule(effect, continuation=_continuation(effect), session_id=parent)
    now = datetime.now(UTC)
    sessions.create_session(
        ClientSession(
            session_id=effect.client_session_id,
            grant=ClientSessionGrant(
                grant_id=uuid4(),
                host_app_id="fixture-host",
                namespace_id="tenant-1",
                frontend_app_id="fixture-web",
                origin="https://app.fixture.example",
                user_ref="user-1",
                profile_digest="a" * 64,
                scopes=("client.action",),
                expires_at=now + timedelta(hours=1),
            ),
            credential_hash="d" * 64,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            ui_revision=effect.expected_ui_revision,
        )
    )
    receipt = _receipt(effect)
    context = ClientPreparationContext(
        operation_id=receipt.receipt_id,
        client_session_id=effect.client_session_id,
        task_id=effect.task_id,
        run_id=effect.run_id,
        projection_version="test:r2",
        request_hash="c" * 64,
        input={
            "threadId": str(effect.task_id),
            "runId": "agui:" + "d" * 64,
            "messages": [],
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {},
        },
        previous_run_id="agui:" + "d" * 64,
    )
    return effect, receipt, context


def test_first_native_receipt_captures_input_on_the_existing_single_resume(stores):
    effect, receipt, context = prepared(stores)
    _, receipts, _, events, dsn, namespace = stores
    args = {
        "request_fence_hash": effect.fence_hash,
        "session_id": effect.parent_session_id,
        "preparation": context,
    }
    accepted = receipts.accept_receipt(receipt, **args)
    before = events.list_for_session(effect.parent_session_id)
    resumes = [e for e in before if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]
    assert len(resumes) == 1
    assert resumes[0].payload["payload"]["input"] == context.input
    assert resumes[0].payload["payload"]["client_preparation"] == context.model_dump(
        mode="json", exclude={"input"}
    )
    cold = PostgresClientEffectReceipts(dsn, deployment_namespace=namespace)
    assert cold.read_receipt(effect.effect_id) == receipt
    duplicate = cold.accept_receipt(receipt, **args)
    assert duplicate.replayed and duplicate.resume_command_id == accepted.resume_command_id
    assert events.list_for_session(effect.parent_session_id) == before
    with pytest.raises(ValueError):
        cold.accept_receipt(
            receipt,
            **{**args, "preparation": context.model_copy(update={"request_hash": "f" * 64})},
        )
    assert events.list_for_session(effect.parent_session_id) == before


def test_native_payload_budget_is_checked_before_receipt_or_resume_write(stores):
    effect, receipt, context = prepared(stores)
    _, receipts, _, events, _, _ = stores
    before = events.list_for_session(effect.parent_session_id)
    context = context.model_copy(update={"input": {"large": "x" * 70_000}})
    with pytest.raises(ValueError):
        receipts.accept_receipt(
            receipt,
            request_fence_hash=effect.fence_hash,
            session_id=effect.parent_session_id,
            preparation=context,
        )
    assert receipts.read_receipt(effect.effect_id) is None
    assert events.list_for_session(effect.parent_session_id) == before


def test_accepted_legacy_receipt_is_not_rewritten_to_attach_new_input(stores):
    effect, receipt, context = prepared(stores)
    _, receipts, _, events, _, _ = stores
    receipts.accept_receipt(
        receipt, request_fence_hash=effect.fence_hash, session_id=effect.parent_session_id
    )
    before = events.list_for_session(effect.parent_session_id)
    with pytest.raises(ValueError):
        receipts.accept_receipt(
            receipt,
            request_fence_hash=effect.fence_hash,
            session_id=effect.parent_session_id,
            preparation=context,
        )
    assert events.list_for_session(effect.parent_session_id) == before
