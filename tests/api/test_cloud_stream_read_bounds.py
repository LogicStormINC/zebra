"""Cloud public replay guards source membership without hydrating historic bodies."""

from types import SimpleNamespace

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_storage import PostgresAgentTaskStore, PostgresEventStore, PostgresProjectionStore
from zebra_agent_api.coverage_public_read import (
    cloud_raw_stream_preflight,
    coverage_session_read_problem,
    coverage_task_read_problem,
)

from tests.agent_storage.test_postgres_agent_tasks import _seed_session
from tests.agent_storage.test_postgres_agent_tasks import postgres_dsn as _dsn_fixture
from tests.agent_storage.test_postgres_agent_tasks import task_namespace as _namespace_fixture

task_namespace = _namespace_fixture
postgres_dsn = _dsn_fixture


@pytest.fixture
def source(postgres_dsn, task_namespace, tmp_path):
    sid = _seed_session(postgres_dsn, task_namespace, tmp_path, "Stream")
    stores = SimpleNamespace(
        deployment_namespace=task_namespace,
        events=PostgresEventStore(postgres_dsn, deployment_namespace=task_namespace),
        tasks=PostgresAgentTaskStore(postgres_dsn, deployment_namespace=task_namespace),
        sessions=PostgresProjectionStore(postgres_dsn, deployment_namespace=task_namespace),
    )
    stores.tasks.ensure_for_session(sid)
    stores.tasks.backfill_replay_headers(TaskId(sid))
    return stores, sid


def append(source, kind, payload):
    stores, sid = source
    event = SessionEvent.create(
        session_id=sid,
        sequence=stores.events.read_session_highwater(sid) + 1,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.HARNESS,
        payload={"title": "Marker"},
    )
    event = event.model_copy(update={"event_type": kind, "payload": payload})
    stores.events.append(event)
    stores.sessions.save_session(rebuild_session(stores.events.list_for_session(sid)))
    return event


def test_source_qualified_preflight_bypasses_historical_body_hydration(source, monkeypatch):
    stores, sid = source
    append(source, EventType.MODEL_RESPONSE_DELTA, {"content_delta": "🙂" * 300_000})
    monkeypatch.setattr(
        SessionEvent,
        "model_validate",
        lambda *args, **kwargs: (pytest.fail("stream startup hydrated a historical body")),
    )
    assert stores.tasks.read_task_header(TaskId(sid)).strict_coverage is None
    header = stores.tasks.read_task_header(TaskId(sid), require_source_coverage=True)
    assert header.strict_coverage is False
    assert coverage_task_read_problem(stores, TaskId(sid)) is None
    assert coverage_session_read_problem(stores, sid) is None
    assert cloud_raw_stream_preflight(stores, f"/tasks/{sid}/stream").status_code == 200


@pytest.mark.parametrize("raw", [None, {}, "malformed"])
def test_late_coverage_presence_suppresses_every_ordinary_prefix(source, raw):
    stores, sid = source
    assert coverage_task_read_problem(stores, TaskId(sid)) is None
    append(source, EventType.TASK_PREPARED, {"coverage_admission": raw})
    assert stores.tasks.read_task_header(TaskId(sid), require_source_coverage=True).strict_coverage
    assert coverage_session_read_problem(stores, sid).body["status"] == "coverage_report_required"


@pytest.mark.parametrize("table", ["session_observation_headers", "task_event_index"])
def test_missing_header_or_index_fails_closed_without_read_repair(
    source,
    postgres_dsn,
    task_namespace,
    table,
):
    stores, sid = source
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(f"DELETE FROM {table} WHERE deployment_namespace=%s", (task_namespace,))
    with pytest.raises((CheckpointConflict, CheckpointNotReady)):
        stores.tasks.read_task_header(TaskId(sid), require_source_coverage=True)
    assert coverage_task_read_problem(stores, TaskId(sid)).status_code == 409
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE deployment_namespace=%s",
                (task_namespace,),
            ).fetchone()[0]
            == 0
        )


def test_unknown_session_membership_fails_closed(source):
    stores, sid = source
    stores.tasks = SimpleNamespace(task_id_for_session=lambda identity: None)
    assert coverage_session_read_problem(stores, sid).status_code == 409


def test_late_coverage_on_predecessor_suppresses_child_segment(
    source,
    postgres_dsn,
    task_namespace,
    tmp_path,
):
    from agent_core.domain.agent_tasks import RolloverReason
    from agent_storage import attach_segment_in_transaction

    stores, root = source
    child = _seed_session(postgres_dsn, task_namespace, tmp_path / "child", "Child")
    with psycopg.connect(postgres_dsn) as connection:
        attach_segment_in_transaction(
            connection,
            task_namespace,
            task_id=TaskId(root),
            segment_id=child,
            predecessor_id=root,
            reason=RolloverReason.RECOVERY,
        )
    stores.tasks.backfill_replay_headers(TaskId(root))
    assert coverage_session_read_problem(stores, child) is None
    append(source, EventType.TASK_PREPARED, {"coverage_admission": None})
    assert coverage_session_read_problem(stores, child).body["status"] == "coverage_report_required"


@pytest.mark.parametrize("field", ["event_position_source_ready", "event_position_source_cursor"])
def test_incomplete_source_membership_cannot_become_public(
    source,
    postgres_dsn,
    task_namespace,
    field,
):
    stores, root = source
    value = False if field.endswith("ready") else -1
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            f"UPDATE execution_segments SET {field}=%s "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (value, task_namespace, root),
        )
    assert coverage_task_read_problem(stores, TaskId(root)).status_code == 409


def test_native_namespace_authorization_never_hydrates_session_projection(source, monkeypatch):
    from zebra_agent_api.tenant_guard import session_tenant_denied

    stores, sid = source
    monkeypatch.setattr(
        stores.sessions, "get_session", lambda *args: pytest.fail("hydrated Session")
    )
    assert stores.sessions.get_session_namespace(sid) == (True, None)
    context = SimpleNamespace(namespace_id="other")
    assert session_tenant_denied(stores.sessions, str(sid), context)


def test_source_deadline_expires_before_any_header_body_read(source):
    from time import monotonic

    from agent_storage.postgres.task_io import task_io_deadline

    stores, sid = source
    with pytest.raises(TimeoutError), task_io_deadline(monotonic() - 1):
        stores.tasks.read_task_header(TaskId(sid), require_source_coverage=True)


@pytest.mark.parametrize("surface", ["sessions", "tasks"])
def test_http_future_cursor_uses_metadata_before_legacy_route_or_body_io(
    source,
    tmp_path,
    monkeypatch,
    surface,
):
    from dataclasses import fields

    from agent_storage import sqlite_control_plane_stores
    from fastapi.testclient import TestClient
    from zebra_agent_api import create_http_app, http
    from zebra_agent_api.routes import RouteAdapter

    from tests.api.test_host_auth_http import _cloud_settings, _FakeHostAuthorizer

    native, sid = source
    local = sqlite_control_plane_stores(tmp_path / "http.sqlite")
    stores = SimpleNamespace(
        **({field.name: getattr(local, field.name) for field in fields(local)} | vars(native)),
        legacy_artifact_control_enabled=False,
    )
    authorizations = []

    async def authorize(request, *args, **kwargs):
        authorizations.append(request.url.path)
        return None

    monkeypatch.setattr(http, "authorize_request", authorize)
    monkeypatch.setattr(http, "tenant_scope_response", lambda *args: None)
    monkeypatch.setattr(
        RouteAdapter, "handle", lambda *args: pytest.fail("legacy full replay route")
    )
    for target, name in [
        (stores.events, "list_for_session"),
        (stores.tasks, "read_events"),
        (stores.sessions, "get_session"),
    ]:
        monkeypatch.setattr(target, name, lambda *args: pytest.fail("unbounded source body IO"))
    application = create_http_app(
        tmp_path / "http.sqlite",
        settings=_cloud_settings("postgresql://unused.invalid/zebra"),
        stores=stores,
        host_grant_authorizer=_FakeHostAuthorizer(),
    )
    path = f"/{surface}/{sid}/stream"
    response = TestClient(application).get(path, params={"after_sequence": 999})
    assert response.status_code == 400
    assert authorizations == [path]


def test_qualified_snapshot_remains_consistent_when_append_commits_between_metadata_reads(
    source,
    postgres_dsn,
    task_namespace,
    monkeypatch,
):
    from agent_storage.postgres import stream_read_preflight
    from agent_storage.postgres.events import append_event_in_transaction
    from agent_storage.postgres.projections import save_session_in_transaction

    stores, sid = source
    before = stores.tasks.read_task_header(TaskId(sid)).current_sequence
    projection = stores.sessions.get_session(sid)
    original = stream_read_preflight.require_stream_source
    event = SessionEvent.create(
        session_id=sid,
        sequence=before + 1,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Concurrent"},
    )

    def committed_between(connection, namespace, task_id, task):
        with psycopg.connect(postgres_dsn, row_factory=psycopg.rows.dict_row) as writer:
            append_event_in_transaction(writer, task_namespace, event)
            save_session_in_transaction(
                writer,
                task_namespace,
                projection.model_copy(update={"current_sequence": before + 1}),
            )
        return original(connection, namespace, task_id, task)

    monkeypatch.setattr(stream_read_preflight, "require_stream_source", committed_between)
    header = stores.tasks.read_task_header(TaskId(sid), require_source_coverage=True)
    assert header.current_sequence == before and header.strict_coverage is False
    assert stores.events.read_session_highwater(sid) == before + 1


@pytest.mark.parametrize(
    "path",
    [
        "/foo/{id}/stream",
        "/sessions/{id}/extra/stream",
        "/tasks/{id}/extra/stream",
        "/sessions/{id}//stream",
        "/tasks//{id}/stream",
        "/sessions/sessions/{id}/stream",
    ],
)
def test_malformed_raw_stream_shapes_never_enter_source_preflight(path):
    from uuid import uuid4

    from starlette.requests import Request
    from zebra_agent_api.http_stream_routing import _is_stream_request

    rendered = path.format(id=uuid4())
    request = Request(
        {"type": "http", "method": "GET", "path": rendered, "headers": [], "query_string": b""}
    )
    assert not _is_stream_request(request)
    result = cloud_raw_stream_preflight(SimpleNamespace(), rendered)
    assert result.status_code == 404


@pytest.mark.parametrize("method", ["GET", "POST", "HEAD"])
def test_unknown_stream_prefix_cannot_use_unrelated_signed_grant_to_read_victim(
    source,
    tmp_path,
    monkeypatch,
    method,
):
    from dataclasses import fields

    from agent_storage import sqlite_control_plane_stores
    from fastapi.testclient import TestClient
    from zebra_agent_api import create_http_app

    from tests.api.test_host_auth_http import _cloud_settings
    from tests.api.test_http_host_preflight import Authorizer
    from tests.api.test_task_resource_binding import verified
    from tests.host_grant_broker.test_grant_broker import _key, _settings

    native, victim = source
    key = _key()
    grant = verified((key, _settings(key)), run="unrelated-run")
    authorizer = Authorizer(grant)
    local = sqlite_control_plane_stores(tmp_path / "prefix.sqlite")
    stores = SimpleNamespace(
        **({field.name: getattr(local, field.name) for field in fields(local)} | vars(native)),
        legacy_artifact_control_enabled=False,
    )
    for target, name in [
        (stores.events, "list_for_session"),
        (stores.events, "read_session_event_page"),
        (stores.tasks, "read_events"),
        (stores.tasks, "read_task_header"),
        (stores.sessions, "get_session"),
    ]:
        monkeypatch.setattr(target, name, lambda *args, **kwargs: pytest.fail("victim read"))
    application = create_http_app(
        tmp_path / "prefix.sqlite",
        settings=_cloud_settings("postgresql://unused.invalid/zebra"),
        stores=stores,
        host_grant_authorizer=authorizer,
    )
    path = f"/foo/{victim}/stream"
    response = TestClient(application).request(
        method, path, headers={"Authorization": "Bearer valid"}
    )
    assert response.status_code == 404
    assert authorizer.consumed == [path]


@pytest.mark.parametrize("shape", ["/sessions/{id}//stream", "/tasks/{id}/extra/stream"])
def test_malformed_normalized_route_is_404_before_adapter_replay(
    source, tmp_path, monkeypatch, shape
):
    from dataclasses import fields

    from agent_storage import sqlite_control_plane_stores
    from fastapi.testclient import TestClient
    from zebra_agent_api import create_http_app, http
    from zebra_agent_api.routes import RouteAdapter

    from tests.api.test_host_auth_http import _cloud_settings, _FakeHostAuthorizer

    native, sid = source
    local = sqlite_control_plane_stores(tmp_path / "malformed.sqlite")
    stores = SimpleNamespace(
        **({field.name: getattr(local, field.name) for field in fields(local)} | vars(native)),
        legacy_artifact_control_enabled=False,
    )

    async def authorized(*args, **kwargs):
        return None

    monkeypatch.setattr(http, "authorize_request", authorized)
    monkeypatch.setattr(RouteAdapter, "handle", lambda *args: pytest.fail("normalized replay"))
    application = create_http_app(
        tmp_path / "malformed.sqlite",
        settings=_cloud_settings("postgresql://unused.invalid/zebra"),
        stores=stores,
        host_grant_authorizer=_FakeHostAuthorizer(),
    )
    assert TestClient(application).get(shape.format(id=sid)).status_code == 404
