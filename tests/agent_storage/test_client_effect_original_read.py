"""Original read is scoped, bounded and cannot write another resume or terminal event."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.client_sessions import ClientSession, ClientSessionGrant
from agent_core.domain.identifiers import new_session_id
from agent_storage.postgres.client_effects import PostgresClientEffectReceipts

from tests.agent_storage.test_postgres_client_effects import (
    _continuation,
    _receipt,
    _request,
    _with_active_lease,
)
from tests.agent_storage.test_postgres_client_effects import (
    stores as stores,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEBRA_TEST_POSTGRES_DSN"), reason="owned PG required"
)


def test_original_receipt_read_is_immutable_and_namespace_scoped(request):
    all_stores = request.getfixturevalue("stores")
    dispatch, receipts, sessions, events, dsn, namespace = all_stores
    parent = new_session_id()
    effect = _with_active_lease(all_stores, _request(parent_session_id=parent))
    dispatch.schedule(effect, continuation=_continuation(effect), session_id=parent)
    assert receipts.read_receipt(effect.effect_id) is None
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
    accepted = receipts.accept_receipt(
        _receipt(effect), request_fence_hash=effect.fence_hash, session_id=parent
    )
    before = [e.model_dump_json() for e in events.list_for_session(parent)]
    with psycopg.connect(dsn) as conn:
        original = conn.execute(
            "SELECT row_to_json(r)::text FROM client_effect_receipts r "
            "WHERE deployment_namespace=%s AND effect_id=%s",
            (namespace, effect.effect_id),
        ).fetchone()[0]
        conn.execute(
            "UPDATE client_control_leases SET released_at=NOW() WHERE deployment_namespace=%s",
            (namespace,),
        )
    assert (
        PostgresClientEffectReceipts(dsn, deployment_namespace="other-" + namespace).read_receipt(
            effect.effect_id
        )
        is None
    )
    for _ in range(3):
        assert receipts.read_receipt(effect.effect_id) == accepted.receipt
        assert dispatch.get_effect(effect.effect_id).request_digest == effect.request_digest
    with psycopg.connect(dsn) as conn:
        after = conn.execute(
            "SELECT row_to_json(r)::text FROM client_effect_receipts r "
            "WHERE deployment_namespace=%s AND effect_id=%s",
            (namespace, effect.effect_id),
        ).fetchone()[0]
    assert after == original
    assert [e.model_dump_json() for e in events.list_for_session(parent)] == before
