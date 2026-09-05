"""Real approval, client receipt and child wakeup producers over the shared seam."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.client_sessions import ClientSession, ClientSessionGrant
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.parent_continuation import ChildTerminalStatus
from agent_storage import PostgresProjectionStore, PostgresWorkspaceProjectionStore
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.client_effects import (
    PostgresClientEffectDispatch,
    PostgresClientEffectReceipts,
)
from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry
from agent_storage.postgres.task_admission import save_task_binding
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService

from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_client_effects import (
    _continuation,
    _receipt,
    _request,
    _with_active_lease,
)
from tests.agent_storage.test_postgres_command_wakeup import (
    NAMESPACE,
    _counts,
    _enable,
    _seed,
    _store,
)
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_dsn_fixture
from tests.agent_storage.test_postgres_concurrent_idempotency import _complete_child, _wakeup_setup

dsn = _dsn_fixture
postgres_dsn = _postgres_dsn_fixture


def _fail_outbox(dsn):
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "ALTER TABLE broker_outbox ADD CONSTRAINT injected_failure CHECK (FALSE)"
        )


def test_real_approval_api_produces_atomic_resume_wakeup(dsn):
    session = _seed(dsn)
    _enable(dsn)
    stores = SimpleNamespace(
        events=_store(dsn),
        sessions=PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE),
        workspaces=PostgresWorkspaceProjectionStore(dsn, deployment_namespace=NAMESPACE),
        tasks=PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE),
    )
    started = SessionEvent.create(
        session_id=session.session_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    )
    stores.events.append(started)
    session = apply_event(session, started)
    stores.sessions.save_session(session)
    workspace = stores.workspaces.get_workspace(session.session_id)
    workspace = apply_workspace_event(workspace, started)
    stores.workspaces.save_workspace(workspace)
    waiting = SessionEvent.create(
        session_id=session.session_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.APPROVAL_REQUESTED,
        actor=EventActor.POLICY,
        payload={"reason": "synthetic approval"},
    )
    stores.events.append(waiting)
    stores.sessions.save_session(apply_event(session, waiting))
    workspace = stores.workspaces.get_workspace(session.session_id)
    stores.workspaces.save_workspace(apply_workspace_event(workspace, waiting))
    app = ZebraAgentApi(database_path=Path("/not-used"), settings=SimpleNamespace(), _stores=stores)
    response = app.approve(str(session.session_id), {"operator": "test", "reason": "approved"})
    assert response.status_code == 200
    stream = stores.events.list_for_session(session.session_id)
    assert stream[-2].event_type is EventType.APPROVAL_GRANTED
    assert stream[-1].event_type is EventType.SESSION_COMMAND_ACCEPTED
    assert stream[-1].payload["kind"] == "resume"
    assert _counts(dsn) == (1, 1)
    # Approval decision commits separately today; only RESUME + derived records are atomic.


def _client_receipt_setup(dsn):
    session = _seed(dsn)
    dispatch = PostgresClientEffectDispatch(dsn, deployment_namespace=NAMESPACE)
    receipts = PostgresClientEffectReceipts(dsn, deployment_namespace=NAMESPACE)
    clients = PostgresClientSessionRegistry(dsn, deployment_namespace=NAMESPACE)
    stores = (dispatch, receipts, clients, _store(dsn), dsn, NAMESPACE)
    request = _with_active_lease(
        stores, _request(parent_session_id=session.session_id, task_id=TaskId(session.session_id))
    )
    dispatch.schedule(request, continuation=_continuation(request), session_id=session.session_id)
    now = datetime.now(UTC)
    clients.create_session(
        ClientSession(
            session_id=request.client_session_id,
            grant=ClientSessionGrant(
                grant_id=uuid4(),
                host_app_id="trench",
                namespace_id="tenant-a",
                frontend_app_id="test",
                origin="https://trench.example",
                user_ref="user-a",
                profile_digest="a" * 64,
                scopes=("client.action",),
                expires_at=now + timedelta(hours=1),
            ),
            credential_hash="d" * 64,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            ui_revision=request.expected_ui_revision,
        )
    )
    _enable(dsn)
    return session, request, receipts


@pytest.mark.parametrize("rollback", [False, True])
def test_real_client_receipt_resume_and_derived_records_share_transaction(dsn, rollback):
    session, request, receipts = _client_receipt_setup(dsn)
    before = _store(dsn).list_for_session(session.session_id)
    if rollback:
        _fail_outbox(dsn)
        with pytest.raises(psycopg.errors.CheckViolation):
            receipts.accept_receipt(
                _receipt(request),
                request_fence_hash=request.fence_hash,
                session_id=session.session_id,
            )
        assert _counts(dsn) == (0, 0)
        assert _store(dsn).list_for_session(session.session_id) == before
        with psycopg.connect(dsn) as connection:
            assert connection.execute("SELECT count(*) FROM client_effect_receipts").fetchone() == (
                0,
            )
            assert connection.execute("SELECT status FROM client_effects").fetchone() == (
                "pending",
            )
    else:
        first = receipts.accept_receipt(
            _receipt(request), request_fence_hash=request.fence_hash, session_id=session.session_id
        )
        replay = receipts.accept_receipt(
            _receipt(request), request_fence_hash=request.fence_hash, session_id=session.session_id
        )
        assert not first.replayed and replay.replayed
        assert first.resume_command_id == replay.resume_command_id
        assert _counts(dsn) == (1, 1)
        with psycopg.connect(dsn) as connection:
            assert connection.execute("SELECT count(*) FROM client_effect_receipts").fetchone() == (
                1,
            )


@pytest.mark.parametrize("rollback", [False, True])
def test_real_child_wakeup_and_terminal_marker_share_transaction(dsn, rollback):
    parent, children = _wakeup_setup(dsn, NAMESPACE, children=1)
    # The generic delegation fixture has no Host authority; add an explicit frozen
    # synthetic binding and its matching projection namespace before opting in.
    binding = _binding(str(parent)).model_copy(update={"binding_revision": 2})
    save_task_binding(
        dsn, deployment_namespace=NAMESPACE, binding=binding, expected_previous_revision=1
    )
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_projections SET namespace_id = %s WHERE session_id = %s",
            ("tenant-a", parent),
        )
    _complete_child(dsn, NAMESPACE, children[0])
    _enable(dsn)
    service = ChildCompletionWakeupService(dsn, deployment_namespace=NAMESPACE)
    before = _store(dsn).list_for_session(parent)
    if rollback:
        _fail_outbox(dsn)
        with pytest.raises(psycopg.errors.CheckViolation):
            service.process_child_terminal(children[0], status=ChildTerminalStatus.COMPLETED)
        assert _counts(dsn) == (0, 0)
        assert _store(dsn).list_for_session(parent) == before
        with psycopg.connect(dsn) as connection:
            assert connection.execute(
                "SELECT terminal_at FROM subagent_delegation_links"
            ).fetchone() == (None,)
    else:
        result = service.process_child_terminal(children[0], status=ChildTerminalStatus.COMPLETED)
        assert result["decision"] == "resume"
        service.process_child_terminal(children[0], status=ChildTerminalStatus.COMPLETED)
        assert _counts(dsn) == (1, 1)
        event = _store(dsn).list_for_session(parent)[-1]
        assert event.payload["kind"] == "resume"
        assert event.idempotency_key != event.payload["idempotency_key"]
        with psycopg.connect(dsn) as connection:
            assert connection.execute(
                "SELECT envelope_json->>'idempotency_key' FROM broker_outbox"
            ).fetchone() == (event.idempotency_key,)
