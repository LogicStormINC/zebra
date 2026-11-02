"""Read original creation receipts without replay or false noncommit proof."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from zebra_agent_api.idempotency import scoped_idempotency_key
from zebra_agent_api.routes import RouteRequest
from zebra_agent_api.task_routes import handle_task_route

from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.api.test_task_principal_guard import TASK_ID, _binding, _context, _verified

postgres_dsn = _pg_fixture
dsn = _dsn_fixture


def app_for(owner):
    records = {}
    app = SimpleNamespace(
        stores=SimpleNamespace(
            deployment_namespace="trench-prod",
            idempotency=SimpleNamespace(
                get=lambda **kw: records.get((kw["action"], kw["idempotency_key"]))
            ),
            sessions=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(namespace_id="trench-prod")
            ),
        ),
        cloud_control=SimpleNamespace(
            deployment_namespace="trench-prod", load_task_binding=lambda _: _binding(owner)
        ),
        settings=SimpleNamespace(database_url="postgresql://unused"),
    )
    return app, records


def lookup(app, context, key="original"):
    return handle_task_route(
        app,
        RouteRequest(
            "GET",
            "/task-admissions/receipt",
            headers={"Idempotency-Key": key},
            host_context=context,
            verified_host_grant=_verified(context),
        ),
    )


def test_positive_receipt_is_scoped_minimal_and_read_only():
    owner = _context("user-a")
    app, records = app_for(owner)
    key = scoped_idempotency_key("original", owner)
    record = SimpleNamespace(
        status_code=201,
        request_hash="a" * 64,
        response_body={
            "session_id": TASK_ID,
            "current_sequence": 2,
            "prompt": "private original prompt",
        },
    )
    records[("session.create", key)] = record
    reply = lookup(app, owner)
    assert reply is not None and reply.status_code == 200
    assert reply.body["status"] == "recorded" and reply.body["task_id"] == TASK_ID
    assert "private" not in str(reply.body) and len(records) == 1
    other = lookup(app, _context("user-b"))
    assert other.body["status"] == "not_observed" and other.body["noncommit_proved"] is False


def test_empty_receipt_never_claims_no_inflight_creation():
    owner = _context("user-a")
    app, _ = app_for(owner)
    reply = lookup(app, owner)
    assert reply is not None and reply.body["status"] == "not_observed"
    assert reply.body["noncommit_proved"] is False


@pytest.mark.parametrize("key", ["", "bad\nkey", "x" * 129])
def test_bad_key_does_not_reach_storage(key):
    owner = _context("user-a")
    app, _ = app_for(owner)
    app.stores.idempotency.get = lambda **_: pytest.fail("invalid key read")
    assert lookup(app, owner, key).status_code == 400


def test_receipt_for_another_thread_is_not_disclosed():
    owner = _context("user-a")
    app, records = app_for(owner)
    other = owner.model_copy(update={"workspace_ref": "other-workspace"})
    records[("session.create", scoped_idempotency_key("original", other))] = SimpleNamespace(
        status_code=201,
        request_hash="a" * 64,
        response_body={"session_id": TASK_ID, "current_sequence": 2},
    )
    assert lookup(app, other).status_code == 404


def test_expired_and_unverified_authority_never_reads_storage():
    owner = _context("user-a")
    app, _ = app_for(owner)
    app.stores.idempotency.get = lambda **_: pytest.fail("unauthorized storage read")
    expired = owner.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    assert lookup(app, expired).status_code == 403
    request = RouteRequest(
        "GET",
        "/task-admissions/receipt",
        headers={"Idempotency-Key": "original"},
        host_context=owner,
    )
    assert handle_task_route(app, request).status_code == 403


def test_storage_outage_is_unknown_never_noncommit():
    app, _ = app_for(_context("user-a"))

    def unavailable(**_):
        raise TimeoutError("private database diagnostics")

    app.stores.idempotency.get = unavailable
    reply = lookup(app, _context("user-a"))
    assert reply.status_code == 503 and reply.body == {"status": "unavailable"}


def test_wrong_thread_positive_receipt_is_not_disclosed():
    owner = _context("user-a")
    app, records = app_for(owner)
    other = owner.model_copy(
        update={
            "resource_refs": tuple(
                ref.model_copy(update={"resource_id": "other-thread"})
                if ref.resource_type == "thread"
                else ref
                for ref in owner.resource_refs
            )
        }
    )
    records[("session.create", scoped_idempotency_key("original", other))] = SimpleNamespace(
        status_code=201,
        request_hash="a" * 64,
        response_body={"session_id": TASK_ID, "current_sequence": 2},
    )
    assert lookup(app, other).status_code == 404


def test_postgres_receipt_lookup_keeps_original_record(dsn):
    from agent_storage.idempotency import new_idempotency_record
    from agent_storage.postgres.idempotency import PostgresIdempotencyStore

    owner = _context("user-a")
    app, _ = app_for(owner)
    store = PostgresIdempotencyStore(dsn, deployment_namespace="trench-prod")
    app.stores.idempotency = store
    key = scoped_idempotency_key("original", owner)
    original = store.save(
        new_idempotency_record(
            action="session.create",
            idempotency_key=key,
            request_hash="a" * 64,
            status_code=201,
            response_body={"session_id": TASK_ID, "current_sequence": 2},
        )
    )
    for _ in range(2):
        assert lookup(app, owner).body["task_id"] == TASK_ID
        assert store.get(action="session.create", idempotency_key=key) == original
    assert lookup(app, _context("user-b")).body["status"] == "not_observed"
