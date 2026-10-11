"""Cloud lists are exact-resource reads, never namespace-wide authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_tasks import AgentTask
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage import PostgresAgentTaskStore, PostgresProjectionStore
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.workspaces import PostgresWorkspaceProjectionStore
from zebra_agent_api.api_session_read_mixin import ApiSessionReadMixin
from zebra_agent_api.routes import RouteRequest
from zebra_agent_api.tenant_guard import tenant_scope_response

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_direct_control import _rows
from tests.agent_storage.test_postgres_task_resource_binding import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_task_resource_binding import (
    postgres_dsn as _postgres_fixture,
)
from tests.api.test_task_resource_binding import TASK, binding_for, verified
from tests.host_grant_broker.test_grant_broker import _key, _settings

OTHER = "22222222-2222-4222-8222-222222222222"
dsn = _dsn_fixture
postgres_dsn = _postgres_fixture


@pytest.fixture(scope="module")
def broker():
    key = _key()
    return key, _settings(key)


class ListApp(ApiSessionReadMixin):
    pass


def app_for(grant, other_grant):
    app = ListApp()
    touched = []
    candidates = tuple(
        AgentTask(
            task_id=TaskId(UUID(key)),
            active_segment_id=SessionId(UUID(key)),
            title=key,
            status=SessionStatus.WAITING_APPROVAL,
            current_sequence=2,
        )
        for key in (TASK, OTHER)
    )
    bindings = {TASK: binding_for(grant), OTHER: binding_for(other_grant, task=OTHER)}

    def forbidden(*args, **kwargs):
        pytest.fail("list must not read events, adopt, repair or enumerate all approvals")

    def tasks(*, limit):
        assert 1 <= limit <= 100
        touched.append(("list", limit))
        return candidates[:limit]

    def session(key):
        touched.append(("session", str(key)))
        assert str(key) == TASK, "foreign summaries must not be hydrated before authorization"
        return Session.create(title="authorized", created_at=datetime.now(UTC)).model_copy(
            update={
                "session_id": SessionId(UUID(TASK)),
                "namespace_id": grant.context.namespace_id,
                "status": SessionStatus.WAITING_APPROVAL,
            }
        )

    app.stores = SimpleNamespace(
        deployment_namespace="test-deployment",
        tasks=SimpleNamespace(
            list_tasks=tasks,
            read_events=forbidden,
            ensure_for_session=forbidden,
            task_id_for_session=lambda key: TaskId(UUID(str(key))),
        ),
        sessions=SimpleNamespace(get_session=session, list_waiting_approval_sessions=forbidden),
        workspaces=SimpleNamespace(get_workspace=lambda key: None),
    )
    app.cloud_control = SimpleNamespace(
        deployment_namespace="test-deployment", load_task_binding=lambda key: bindings[str(key)]
    )
    return app, touched


@pytest.mark.parametrize("path", ["/sessions", "/approvals", "/tasks"])
def test_list_filters_same_principal_same_namespace_before_summary_reads(broker, path):
    grant = verified(broker, run="fresh-read-run")
    other = verified(broker, thread="other-opaque-thread")
    app, touched = app_for(grant, other)
    response = tenant_scope_response(
        app, RouteRequest("GET", path, host_context=grant.context, verified_host_grant=grant)
    )
    assert response is not None and response.status_code == 200
    key = "approvals" if path == "/approvals" else "sessions" if path == "/sessions" else "tasks"
    assert [item["session_id"] for item in response.body[key]] == [TASK]
    assert response.body.get("count", 1) == 1
    assert touched.count(("session", TASK)) == 1
    assert all(item != ("session", OTHER) for item in touched)


def test_cloud_list_requires_verified_issuer_not_an_envelope_alone(broker):
    grant = verified(broker)
    app, touched = app_for(grant, verified(broker, thread="other"))
    response = tenant_scope_response(
        app, RouteRequest("GET", "/sessions", host_context=grant.context)
    )
    assert response is not None and response.status_code == 403
    assert not touched
    response = tenant_scope_response(
        app,
        RouteRequest(
            "GET",
            "/sessions",
            host_context=grant.context,
            verified_host_grant=replace(grant, authority_issuer="https://foreign.test"),
        ),
    )
    assert response is not None and response.status_code == 200
    assert response.body["sessions"] == []
    assert not any(kind == "session" for kind, value in touched)


@pytest.mark.parametrize(
    "problem,status",
    [(CheckpointNotReady("pending"), 409), (RuntimeError("storage unavailable"), 503)],
)
def test_list_keeps_readiness_and_storage_failures_distinct(broker, problem, status):
    grant = verified(broker)
    app, touched = app_for(grant, verified(broker, thread="other"))

    def load(_):
        raise problem

    app.cloud_control.load_task_binding = load
    response = tenant_scope_response(
        app,
        RouteRequest("GET", "/approvals", host_context=grant.context, verified_host_grant=grant),
    )
    assert response is not None and response.status_code == status
    assert not any(kind == "session" for kind, value in touched)


def test_list_rechecks_expiry_before_releasing_a_success(broker, monkeypatch):
    grant = verified(broker)
    app, touched = app_for(grant, verified(broker, thread="other"))
    read = app.stores.sessions.get_session

    class Expired(datetime):
        @classmethod
        def now(cls, tz=None):
            return grant.context.expires_at + timedelta(seconds=1)

    def session(key):
        value = read(key)
        monkeypatch.setattr("zebra_agent_api.api_session_read_mixin.datetime", Expired)
        return value

    app.stores.sessions.get_session = session
    response = tenant_scope_response(
        app, RouteRequest("GET", "/sessions", host_context=grant.context, verified_host_grant=grant)
    )
    assert response is not None and response.status_code == 403


@pytest.mark.parametrize("path", ["/sessions", "/approvals", "/tasks"])
def test_native_lists_authorize_before_hydration_and_leave_durable_state_unchanged(
    dsn, broker, path, tmp_path, monkeypatch
):
    grant = verified(broker, run="current-read")

    def seed(current):
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="native resource list",
                user_input="public input",
                workspace_root=tmp_path,
                host_context=current.context,
            )
        )
        started = SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=len(bootstrap.events),
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
        pause = SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=started.sequence + 1,
            event_type=EventType.APPROVAL_REQUESTED,
            actor=EventActor.HARNESS,
            payload={},
        )
        events = (*bootstrap.events, started, pause)
        PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
            TaskAdmissionRequest(
                events=events,
                session=rebuild_session(list(events)),
                workspace=rebuild_workspace(list(events)),
                binding=binding_for(current, task=str(bootstrap.session.session_id)),
            )
        )
        return bootstrap.session.session_id

    allowed = seed(grant)
    seed(verified(broker, thread="same-principal-foreign-thread"))
    app = ListApp()
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE)
    sessions = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    app.stores = SimpleNamespace(
        deployment_namespace=NAMESPACE,
        tasks=tasks,
        sessions=sessions,
        workspaces=PostgresWorkspaceProjectionStore(dsn, deployment_namespace=NAMESPACE),
    )
    app.cloud_control = PostgresDirectControl(dsn, deployment_namespace=NAMESPACE)

    def forbidden(*args, **kwargs):
        pytest.fail("native GET must not hydrate source events, adopt or repair")

    read_session = sessions.get_session

    def authorized_session(key):
        assert key == allowed, "foreign summary was hydrated before authorization"
        return read_session(key)

    monkeypatch.setattr(sessions, "get_session", authorized_session)
    monkeypatch.setattr(sessions, "list_waiting_approval_sessions", forbidden)
    monkeypatch.setattr(tasks, "read_events", forbidden)
    monkeypatch.setattr(tasks, "ensure_for_session", forbidden)
    tables = (
        "session_events",
        "task_binding_snapshots",
        "direct_control_operations",
        "agent_tasks",
        "execution_segments",
        "task_event_index",
    )
    before = tuple(_rows(dsn, table) for table in tables)
    response = tenant_scope_response(
        app, RouteRequest("GET", path, host_context=grant.context, verified_host_grant=grant)
    )
    assert response is not None and response.status_code == 200
    key = "approvals" if path == "/approvals" else "tasks" if path == "/tasks" else "sessions"
    assert [item["session_id"] for item in response.body[key]] == [str(allowed)]
    assert before == tuple(_rows(dsn, table) for table in tables)
