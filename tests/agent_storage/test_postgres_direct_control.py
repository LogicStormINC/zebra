"""Direct cancellation atomically revokes execution without an engine call."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventType
from agent_core.domain.execution_authority import ExecutionAuthoritySnapshot
from agent_storage.postgres import session_cancellation
from agent_storage.postgres.command_runtime_cleanup import settle_runtime_cleanup
from agent_storage.postgres.direct_control import PostgresDirectControl
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_command_runtime_cleanup import _claim
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_runtime_instances import SCOPE, _instances, _setup

dsn = _dsn_fixture
postgres_dsn = _pg_fixture
WORKSPACE = _binding("test").host_capability.host_context.workspace_ref


def _cancel(dsn, session, **kwargs):
    return PostgresDirectControl(dsn, deployment_namespace=NAMESPACE).cancel(
        session,
        scope=kwargs.pop("scope", SCOPE),
        workspace_ref=kwargs.pop("workspace_ref", WORKSPACE),
        **kwargs,
    )


def _rows(dsn, table):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return connection.execute(
            psycopg.sql.SQL("SELECT * FROM {}").format(psycopg.sql.Identifier(table))
        ).fetchall()


def test_direct_cancel_and_explicit_replay_use_one_exact_cleanup_anchor(dsn):
    lease = _setup(dsn)
    instance = str(uuid4())
    runtime = _instances(dsn, lease)
    runtime.reserve(instance, str(lease.session_id), "d" * 64)
    runtime.created(instance, "b" * 64)
    operation = uuid4()
    result = _cancel(dsn, lease.session_id, operation_id=operation)
    assert result.event.event_type is EventType.SESSION_CANCELLED
    assert result.event.causation_id is None
    before = _rows(dsn, "session_events")
    assert _cancel(dsn, lease.session_id, operation_id=operation) == result
    assert _rows(dsn, "session_events") == before
    assert _rows(dsn, "worker_leases")[0]["released_at"] is not None
    obligation = _rows(dsn, "command_runtime_cleanup")[0]
    assert obligation["direct_operation_id"] == operation
    assert obligation["accepted_event_id"] is None
    claim = _claim(dsn)
    assert claim.direct_operation_id == operation and claim.accepted_event_id is None
    assert claim.cleanup_id == obligation["cleanup_id"] and claim.target is not None
    assert settle_runtime_cleanup(dsn, claim, removed_container_id="b" * 64)
    assert _rows(dsn, "command_runtime_cleanup")[0]["status"] == "done"


def test_header_replay_and_no_header_terminal_conflict(dsn):
    lease = _setup(dsn)
    result = _cancel(dsn, lease.session_id, idempotency_key="request")
    assert _cancel(dsn, lease.session_id, idempotency_key="request") == result
    with pytest.raises(ValueError, match="current state"):
        _cancel(dsn, lease.session_id)
    other = _seed(dsn)
    with pytest.raises(ValueError, match="idempotency conflict"):
        _cancel(dsn, other.session_id, idempotency_key="request")
    assert not any(
        e.event_type is EventType.SESSION_CANCELLED
        for e in _store(dsn).list_for_session(other.session_id)
    )


@pytest.mark.parametrize("change", ["scope", "issuer", "workspace", "allowed"])
def test_wrong_caller_never_revokes_or_mutates(dsn, change):
    lease = _setup(dsn)
    kwargs = (
        {"workspace_ref": "wrong"}
        if change == "workspace"
        else {
            "scope": SCOPE.model_copy(
                update={"namespace_id": "other"}
                if change == "scope"
                else {"authority_issuer": "other"}
                if change == "issuer"
                else {"allowed_session_ids": ()}
            )
        }
    )
    before = _rows(dsn, "worker_leases"), _rows(dsn, "session_events")
    with pytest.raises(ValueError):
        _cancel(dsn, lease.session_id, **kwargs)
    assert (_rows(dsn, "worker_leases"), _rows(dsn, "session_events")) == before
    assert not _rows(dsn, "direct_control_operations")


def test_projection_failure_rolls_back_terminal_and_revocation(dsn, monkeypatch):
    lease = _setup(dsn)
    before = _rows(dsn, "worker_leases"), _rows(dsn, "session_events")

    def fail(*args):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(session_cancellation, "save_workspace_in_transaction", fail)
    with pytest.raises(RuntimeError, match="injected"):
        _cancel(dsn, lease.session_id)
    assert (_rows(dsn, "worker_leases"), _rows(dsn, "session_events")) == before
    assert not _rows(dsn, "direct_control_operations")
    assert not _rows(dsn, "command_runtime_cleanup")


def test_same_identity_restricted_reissued_scope_replays(dsn):
    lease = _setup(dsn)
    first = _cancel(dsn, lease.session_id, idempotency_key="request")
    refreshed = SCOPE.model_copy(update={"allowed_session_ids": (str(lease.session_id),)})
    assert _cancel(dsn, lease.session_id, scope=refreshed, idempotency_key="request") == first


@pytest.mark.parametrize("wrong_issuer", [False, True])
def test_generic_no_binding_uses_canonical_identity_not_expired_execution_permission(
    dsn, wrong_issuer
):
    lease = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("DELETE FROM task_binding_snapshots")
        payload = connection.execute("""SELECT payload FROM session_events
            WHERE event_type='execution_authority_resolved'""").fetchone()[0]
        now = datetime.now(UTC)
        payload.update(
            issued_at=now - timedelta(minutes=4),
            validated_at=now - timedelta(minutes=3),
            expires_at=now - timedelta(minutes=1),
            snapshot_digest=None,
        )
        snapshot = ExecutionAuthoritySnapshot.model_validate(payload)
        connection.execute(
            """UPDATE session_events SET payload=%s
            WHERE event_type='execution_authority_resolved'""",
            (Jsonb(snapshot.model_dump(mode="json")),),
        )
        connection.execute(
            """UPDATE worker_leases SET acquired_at=clock_timestamp()-interval '3 seconds',
               heartbeat_at=clock_timestamp()-interval '2 seconds',
               expires_at=clock_timestamp()-interval '1 second'"""
        )
    scope = SCOPE.model_copy(update={"authority_issuer": "wrong"}) if wrong_issuer else SCOPE
    if wrong_issuer:
        with pytest.raises(ValueError, match="identity is unproven"):
            _cancel(dsn, lease.session_id, scope=scope, workspace_ref=None)
        assert not _rows(dsn, "direct_control_operations")
    else:
        result = _cancel(
            dsn, lease.session_id, scope=scope, workspace_ref=None, idempotency_key="retry"
        )
        assert _cancel(dsn, lease.session_id, workspace_ref=None, idempotency_key="retry") == result


def test_pre_execution_host_bound_session_needs_no_execution_authority(dsn):
    from agent_storage import bootstrap_control_plane_epoch

    session = _seed(dsn)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    result = _cancel(dsn, session.session_id)
    assert result.event.event_type is EventType.SESSION_CANCELLED


def test_generic_unproven_issuer_fails_closed(dsn):
    from agent_storage import bootstrap_control_plane_epoch

    session = _seed(dsn)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    with psycopg.connect(dsn) as connection:
        connection.execute("DELETE FROM task_binding_snapshots")
    with pytest.raises(ValueError, match="identity is unproven"):
        _cancel(dsn, session.session_id, workspace_ref=None)
    assert not _rows(dsn, "direct_control_operations")
