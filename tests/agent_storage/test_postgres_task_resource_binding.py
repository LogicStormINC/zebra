"""Real isolated PG: precise resource fence before durable cancellation."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventType
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.task_bindings import host_context_digest
from agent_storage.postgres.direct_control import PostgresDirectControl, _host_scope
from agent_storage.postgres.task_admission import save_task_binding
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_agent_tasks import (
    _append_handoff_events,
    _seed_session,
    _store,
)
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_direct_control import _rows

dsn = _dsn_fixture
THREAD = "trench-bootstrap-native-opaque"


@pytest.fixture(scope="module")
def postgres_dsn():
    configured = os.environ.get("ZEBRA_HEADER_SCRATCH_DSN")
    if not configured:
        pytest.skip("requires explicit isolated header_scratch DSN")
    settings = conninfo_to_dict(configured)
    assert settings.get("dbname") == "header_scratch"
    assert settings.get("host") in {"127.0.0.1", "localhost"}
    assert settings.get("port") == "32786"
    return configured


def _native_case(dsn):
    session = _seed(dsn)
    binding = _binding(str(session.session_id))
    original = binding.host_capability.host_context
    assert original is not None
    current = original.model_copy(
        update={
            "resource_refs": original.resource_refs
            + (
                HostResourceRef(type="thread", id=THREAD),
                HostResourceRef(type="run", id="new-run"),
            ),
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        }
    )
    # The frozen execution Grant is expired; current cancellation authority is fresh.
    old = current.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(minutes=1)})
    binding = binding.model_copy(
        update={
            "binding_revision": 2,
            "host_capability": binding.host_capability.model_copy(
                update={
                    "host_context": old,
                    "grant_digest": host_context_digest(old),
                    "grant_expires_at": old.expires_at,
                }
            ),
        }
    )
    save_task_binding(
        dsn, deployment_namespace=NAMESPACE, binding=binding, expected_previous_revision=1
    )
    return session, current


@pytest.mark.parametrize("thread", ["wrong", "missing", "uuid", "ambiguous"])
def test_wrong_task_resource_cannot_cancel_even_with_previously_obtained_scope(dsn, thread):
    session, current = _native_case(dsn)
    control = PostgresDirectControl(dsn, deployment_namespace=NAMESPACE)
    scope = control.host_scope(session.session_id, current)
    refs = tuple(ref for ref in current.resource_refs if ref.resource_type != "thread")
    if thread != "missing":
        refs += (
            HostResourceRef(
                type="thread", id=str(session.session_id) if thread == "uuid" else "wrong"
            ),
        )
    if thread == "ambiguous":
        refs += (HostResourceRef(type="thread", id=THREAD),)
    forged = current.model_copy(update={"resource_refs": refs})
    before = _rows(dsn, "session_events"), _rows(dsn, "direct_control_operations")
    with pytest.raises(ValueError):
        control.host_scope(session.session_id, forged)
    with pytest.raises(ValueError):
        control.cancel(
            session.session_id,
            scope=scope,
            workspace_ref=current.workspace_ref,
            host_context=forged,
        )
    assert before == (_rows(dsn, "session_events"), _rows(dsn, "direct_control_operations"))
    assert not _rows(dsn, "command_runtime_cleanup")


def test_correct_current_grant_cancels_without_renewing_expired_binding(dsn):
    session, current = _native_case(dsn)
    control = PostgresDirectControl(dsn, deployment_namespace=NAMESPACE)
    scope = control.host_scope(session.session_id, current)
    bindings = _rows(dsn, "task_binding_snapshots")
    result = control.cancel(
        session.session_id, scope=scope, workspace_ref=current.workspace_ref, host_context=current
    )
    assert result.event.event_type is EventType.SESSION_CANCELLED
    assert len(_rows(dsn, "direct_control_operations")) == 1
    assert bindings == _rows(dsn, "task_binding_snapshots")


def test_native_rollover_session_resolves_root_binding_not_child_uuid(postgres_dsn):
    schema = f"resource_rollover_{uuid4().hex}"
    root, child = uuid4(), uuid4()
    binding = _binding(str(root))
    current = binding.host_capability.host_context
    assert current is not None
    current = current.model_copy(
        update={
            "expires_at": datetime.now(UTC) + timedelta(minutes=1),
            "resource_refs": current.resource_refs
            + (
                HostResourceRef(type="thread", id=THREAD),
                HostResourceRef(type="run", id="later-run"),
            ),
        }
    )
    binding = binding.model_copy(
        update={
            "host_capability": binding.host_capability.model_copy(
                update={
                    "host_context": current,
                    "grant_digest": host_context_digest(current),
                }
            )
        }
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        with psycopg.connect(postgres_dsn, row_factory=psycopg.rows.dict_row) as connection:
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            connection.execute(
                "CREATE TABLE execution_segments "
                "(deployment_namespace text, session_id uuid, task_id uuid)"
            )
            connection.execute(
                "CREATE TABLE task_binding_snapshots (deployment_namespace text, task_id uuid, "
                "binding_revision integer, snapshot_json jsonb)"
            )
            connection.execute(
                "INSERT INTO execution_segments VALUES (%s,%s,%s)", (NAMESPACE, child, root)
            )
            connection.execute(
                "INSERT INTO task_binding_snapshots VALUES (%s,%s,1,%s)",
                (NAMESPACE, root, Jsonb(binding.model_dump(mode="json"))),
            )
            scope = _host_scope(connection, NAMESPACE, child, current)
            assert scope.allowed_session_ids == (str(child),)
            uuid_context = current.model_copy(
                update={
                    "resource_refs": tuple(
                        HostResourceRef(type="thread", id=str(child))
                        if ref.resource_type == "thread"
                        else ref
                        for ref in current.resource_refs
                    )
                }
            )
            with pytest.raises(ValueError):
                _host_scope(connection, NAMESPACE, child, uuid_context)
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_scalar_task_lookup_uses_existing_index_and_namespace(dsn, tmp_path, monkeypatch):
    root = _seed_session(dsn, NAMESPACE, tmp_path / "root", "Root")
    child = _seed_session(dsn, NAMESPACE, tmp_path / "child", "Child")
    _append_handoff_events(dsn, NAMESPACE, root=root, child=child)
    store = _store(dsn, NAMESPACE)
    task = store.ensure_for_session(child)

    def no_hydration(*args, **kwargs):
        raise AssertionError("identity read hydrated or adopted Task history")

    monkeypatch.setattr(store, "get_task", no_hydration)
    monkeypatch.setattr(store, "read_events", no_hydration)
    monkeypatch.setattr(store, "ensure_for_session", no_hydration)
    assert store.task_id_for_session(root) == task.task_id
    assert store.task_id_for_session(child) == task.task_id
    assert store.is_internal_segment(child)
    assert not store.is_internal_segment(root)
    foreign = _store(dsn, f"unmapped-{uuid4()}")
    assert foreign.task_id_for_session(root) is None
    assert foreign.task_id_for_session(child) is None
