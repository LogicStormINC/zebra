"""Native admission/Handoff lock-order regression, only in a disposable PG DB."""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any, Literal
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.identifiers import TaskId
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    PostgresSessionHandoffStore,
    PostgresWorkspaceProjectionStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.event_rows import SessionEventSequenceConflictError
from agent_storage.postgres import events as event_module
from agent_storage.postgres.extension_snapshots import (
    PostgresExtensionSnapshotStore,
    resolve_extension_task_ceiling_in_transaction,
)
from agent_storage.postgres.task_admission import (
    PostgresTaskAdmissionTransaction,
    save_task_binding,
)
from agent_storage.session_handoff_rows import HandoffStorageConflictError
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from tests.agent_integrations.binding_store_cases import BindingStores, prepare_native, ready
from tests.agent_storage.test_postgres_projection_source_metadata import (
    metadata_dsn as metadata_dsn,
)
from tests.agent_storage.test_postgres_task_admission import _binding, _request


def _outcome(operation: Callable[[], object]) -> str:
    try:
        operation()
        return "committed"
    except (SessionEventSequenceConflictError, HandoffStorageConflictError) as error:
        return type(error).__name__
    except psycopg.Error as error:
        return error.sqlstate or type(error).__name__  # Never expose DSN/diagnostic details.


def _wait_blocked(
    dsn: str, application: str, blocker: int, done: Callable[[], bool] | None = None
) -> str:
    with psycopg.connect(dsn, autocommit=True) as observer:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            blocked = observer.execute(
                """SELECT CASE
                     WHEN strpos(query,'workspace_projections')>0 THEN 'workspace'
                     WHEN strpos(query,'execution_segments')>0 THEN 'segment'
                     WHEN strpos(query,'session_streams')>0 THEN 'stream'
                     WHEN strpos(query,'pg_advisory')>0 THEN 'advisory'
                     WHEN query='COMMIT' THEN 'deferred'
                     ELSE 'other' END
                   FROM pg_stat_activity WHERE datname=current_database()
                   AND application_name=%s AND %s=ANY(pg_blocking_pids(pid))""",
                (application, blocker),
            ).fetchone()
            if blocked is not None:
                return str(blocked[0])  # Return a fixed label, never SQL/payload text.
            if done is not None and done():
                return "completed"
            time.sleep(0.01)
    pytest.fail("native Handoff never reached the held admission boundary")


@pytest.mark.parametrize("other_writer", ("handoff", "append", "maintenance"))
def test_native_extension_admission_and_source_writer_do_not_deadlock(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    other_writer: Literal["handoff", "append", "maintenance"],
) -> None:
    task_dsn = request.getfixturevalue("metadata_dsn")
    assert isinstance(task_dsn, str)
    namespace = f"source-lock-order-{uuid4().hex}"
    bootstrap_control_plane_epoch(task_dsn, deployment_namespace=namespace)
    # Test-local timeouts bound both threads; no server/global settings change.
    options = "-c statement_timeout=10000 -c lock_timeout=6000 -c deadlock_timeout=100"
    application = f"native-source-writer-{uuid4().hex}"
    admission_dsn = make_conninfo(task_dsn, options=options)
    handoff_dsn = make_conninfo(task_dsn, options=options, application_name=application)
    tasks = PostgresAgentTaskStore(task_dsn, deployment_namespace=namespace)
    events = PostgresEventStore(admission_dsn, deployment_namespace=namespace)
    handoffs = PostgresSessionHandoffStore(handoff_dsn, deployment_namespace=namespace)
    stores = BindingStores(
        tasks,
        events,
        PostgresProjectionStore(task_dsn, deployment_namespace=namespace),
        PostgresWorkspaceProjectionStore(task_dsn, deployment_namespace=namespace),
        handoffs,
        namespace,
        lambda: PostgresAgentTaskStore(task_dsn, deployment_namespace=namespace),
    )
    handoff_request = prepare_native(stores, tmp_path)
    source = handoff_request.operation.source_session_id
    task = TaskId(source)
    run = ready(tasks, task)
    frozen = tuple(tasks.read_event_header(task, n) for n in range(run.highwater + 1))
    # Existing local fixture binding has no Host context; no execution grant is minted.
    save_task_binding(task_dsn, deployment_namespace=namespace, binding=_binding(str(task)))
    ceiling = PostgresExtensionSnapshotStore(
        task_dsn, deployment_namespace=namespace
    ).resolve_task_ceiling(session_id=str(source))
    scope = ExtensionScope(
        authority_issuer="https://fixture.example.com",
        namespace_id="fixture",
        principal_id="fixture",
        workspace_id="fixture",
    )
    snapshot = ExtensionSnapshot(scope=scope, session_id=str(source), turn_id=str(uuid4()))
    if other_writer == "maintenance":
        # Resume an already assigned Segment's metadata frontier, not its positions.
        with psycopg.connect(task_dsn) as setup:
            setup.execute(
                """UPDATE agent_tasks SET event_position_state='assigning'
                   WHERE deployment_namespace=%s AND task_id=%s""",
                (namespace, task),
            )
            setup.execute(
                """UPDATE execution_segments SET event_position_source_ready=false
                   WHERE deployment_namespace=%s AND session_id=%s""",
                (namespace, source),
            )
    command = SessionEvent.create(
        session_id=source,
        sequence=6,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.HARNESS,
        idempotency_key="source-lock-probe",
        payload={
            "command_id": str(uuid4()),
            "session_id": str(source),
            "kind": "run",
            "payload": {"run_id": "lock-probe"},
            "expected_revision": 5,
            "idempotency_key": "source-lock-probe",
            "fingerprint": "a" * 64,
            "extension_turn_id": snapshot.turn_id,
            "extension_snapshot_digest": snapshot.digest,
        },
    )

    def competing() -> object:
        if other_writer == "handoff":
            return handoffs.commit(handoff_request)
        if other_writer == "maintenance":
            assert PostgresAgentTaskStore(
                handoff_dsn, deployment_namespace=namespace
            ).backfill_event_positions(task)
            return None
        return PostgresEventStore(handoff_dsn, deployment_namespace=namespace).append(
            SessionEvent.create(
                session_id=source,
                sequence=6,
                event_type=EventType.SESSION_TITLE_UPDATED,
                actor=EventActor.HARNESS,
                payload={"title": "native deferred append"},
            )
        )

    entered, release = Event(), Event()
    admission_pid: list[int] = []

    def pause_admission(
        connection: Any, deployment_namespace: str, session_id: str
    ) -> ExtensionTaskCeiling:
        current = resolve_extension_task_ceiling_in_transaction(
            connection, deployment_namespace, session_id
        )
        admission_pid.append(connection.info.backend_pid)
        entered.set()
        assert release.wait(8), "admission probe barrier timed out"
        return current

    monkeypatch.setattr(
        event_module, "resolve_extension_task_ceiling_in_transaction", pause_admission
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        admission = pool.submit(
            _outcome,
            lambda: events.append_with_extension_snapshot(
                command, scope=scope, snapshot=snapshot, task_ceiling=ceiling
            ),
        )
        try:
            assert entered.wait(5), "native admission did not resolve its Task ceiling"
            writer = pool.submit(_outcome, competing)
            boundary = _wait_blocked(
                task_dsn,
                application,
                admission_pid[0],
                writer.done if other_writer == "maintenance" else None,
            )
            with psycopg.connect(task_dsn) as observer:
                acquired = observer.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,61))",
                    (f"{namespace}:{task}",),
                ).fetchone()
                assert acquired is not None
                task61_held = not acquired[0]
            if boundary == "deferred":
                assert task61_held, "deferred producer did not own its Task61 boundary"
        finally:
            release.set()
        outcomes = (admission.result(timeout=12), writer.result(timeout=12))
    # A stream/lineage CAS loser is legitimate; a DB deadlock is not.
    assert "40P01" not in outcomes, (
        f"native source lock-order deadlock: writer={other_writer}, "
        f"blocked_at={boundary}, Task61_held={task61_held}, outcomes={outcomes}"
    )
    assert tuple(tasks.read_event_header(task, n) for n in range(run.highwater + 1)) == frozen
    assert set(outcomes) <= {
        "committed",
        "SessionEventSequenceConflictError",
        "HandoffStorageConflictError",
    }, outcomes
    assert outcomes.count("committed") == (2 if other_writer == "maintenance" else 1)


def test_admission_key_share_still_protects_segment_membership_deletion(
    request: pytest.FixtureRequest,
) -> None:
    task_dsn = request.getfixturevalue("metadata_dsn")
    assert isinstance(task_dsn, str)
    namespace = f"source-membership-lock-{uuid4().hex}"
    bootstrap_control_plane_epoch(task_dsn, deployment_namespace=namespace)
    admission = _request()
    source = str(admission.session.session_id)
    PostgresTaskAdmissionTransaction(task_dsn, deployment_namespace=namespace).admit(
        replace(admission, binding=_binding(source))
    )
    with psycopg.connect(task_dsn, row_factory=dict_row) as authority:
        assert resolve_extension_task_ceiling_in_transaction(authority, namespace, source)
        with psycopg.connect(task_dsn) as deleter:
            deleter.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                deleter.execute(
                    """DELETE FROM execution_segments
                       WHERE deployment_namespace=%s AND session_id=%s""",
                    (namespace, source),
                )
            deleter.rollback()
            remaining = deleter.execute(
                """SELECT task_id FROM execution_segments
                   WHERE deployment_namespace=%s AND session_id=%s""",
                (namespace, source),
            ).fetchone()
            assert remaining is not None and str(remaining[0]) == source
