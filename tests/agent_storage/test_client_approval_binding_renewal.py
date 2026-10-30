"""Real PG renewal/approval ordering; current-session authorization tested separately."""

from contextlib import contextmanager
from dataclasses import fields, replace
from types import SimpleNamespace
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.task_admission import load_task_binding, save_task_binding
from zebra_agent_api import client_approval_operations as api
from zebra_agent_api.session_binding import _build_binding_snapshot

from tests.agent_storage.test_client_approval_operations import fixture
from tests.agent_storage.test_postgres_migrations import isolated_migration_dsn as _isolated
from tests.agent_storage.test_postgres_migrations import postgres_dsn as _postgres
from tests.api.test_session_binding_renewal import _context, _verified

isolated_migration_dsn = _isolated
postgres_dsn = _postgres


def test_fresh_binding_persists_before_approval_lock_and_get_never_renews(
    isolated_migration_dsn, tmp_path, monkeypatch
):
    app, request, seed = fixture(isolated_migration_dsn, tmp_path, monkeypatch)
    app.settings = SimpleNamespace(
        deployment="cloud", storage_authority="postgresql", database_url=isolated_migration_dsn
    )
    app.stores = SimpleNamespace(
        **{field.name: getattr(app.stores, field.name) for field in fields(app.stores)},
        deployment_namespace="approval-op",
    )
    task = TaskId(UUID(request.path.split("/")[3]))
    original = _context(grant_id="adoption")
    initial = _build_binding_snapshot(
        str(task),
        host_context=original,
        verified_host_grant=_verified(original),
        definition_snapshot_digest="a" * 64,
    )
    save_task_binding(isolated_migration_dsn, deployment_namespace="approval-op", binding=initial)
    fresh = _context(grant_id="approval-fresh")
    request = replace(request, host_context=fresh, verified_host_grant=_verified(fresh))
    unit = app.stores.events.approval_operation_unit
    observed = []

    def binding():
        return load_task_binding(
            isolated_migration_dsn, deployment_namespace="approval-op", task_id=task
        )

    @contextmanager
    def checked_unit(segment):
        current = binding()
        assert current.binding_revision == 2
        assert current.host_capability.host_context == fresh
        assert current.agent_capability_ceiling == initial.agent_capability_ceiling
        observed.append(current)
        with unit(segment):
            yield

    monkeypatch.setattr(app.stores.events, "approval_operation_unit", checked_unit)
    response = api.handle_client_approval_operation(app, request)
    assert response.status_code == 200, response
    assert len(observed) == 1
    events = app.stores.events.list_for_session(seed.session_id)
    assert len(events) == seed.current_sequence + 3
    receipt = api.handle_client_approval_operation(app, replace(request, method="GET", body=None))
    assert receipt.body == response.body
    assert binding() == observed[0]
    assert app.stores.events.list_for_session(seed.session_id) == events
