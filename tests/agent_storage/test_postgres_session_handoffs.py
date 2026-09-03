from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import agent_storage.postgres.session_handoff_transactions as handoff_transactions
import psycopg
import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.session_handoff import (
    HandoffActorKind,
    HandoffReason,
    SessionHandoffEnvelope,
)
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS
from agent_core.ports.session_handoff import (
    HandoffOperation,
    HandoffSourceFacts,
    SessionHandoffAbortRequest,
    SessionHandoffCommitRequest,
    SessionHandoffCreateRequest,
    canonical_handoff_request_hash,
)
from agent_storage import (
    HandoffIdempotencyConflictError,
    HandoffStorageConflictError,
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresSessionHandoffStore,
    PostgresWorkspaceProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)

NOW = datetime(2026, 7, 29, 0, 0, tzinfo=UTC)
OBJECTIVE = "Continue the staged task"
COMPLETED_WORK = ("source complete",)
PENDING_WORK = ("storage",)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def handoff_namespace(postgres_dsn: str) -> Generator[str]:
    namespace = f"handoff-aggregate-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_commit_persists_the_complete_handoff_aggregate(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, request = _prepared_commit(store, source_id)

    result = store.commit(request)

    assert result.child_session_id == operation.target_session_id
    assert result.child_status == "ready"
    assert result.idempotent_replay is False
    assert store.get_envelope(operation.handoff_id) == request.envelope
    assert store.get_handoff(operation.handoff_id) == result
    assert [item.session_id for item in store.get_lineage(result.child_session_id)] == [
        source_id,
        operation.target_session_id,
    ]
    events = PostgresEventStore(postgres_dsn, deployment_namespace=handoff_namespace)
    assert events.list_for_session(source_id)[-1].event_type is EventType.SESSION_HANDOFF_COMMITTED
    assert [event.event_type for event in events.list_for_session(result.child_session_id)] == [
        EventType.SESSION_CREATED,
        EventType.SESSION_HANDOFF_RECEIVED,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
    ]
    sessions = PostgresProjectionStore(postgres_dsn, deployment_namespace=handoff_namespace)
    workspaces = PostgresWorkspaceProjectionStore(
        postgres_dsn,
        deployment_namespace=handoff_namespace,
    )
    child = sessions.get_session(result.child_session_id)
    child_workspace = workspaces.get_workspace(result.child_session_id)
    assert child is not None and child.current_sequence == 3
    assert child_workspace is not None and child_workspace.workspace_root == str(tmp_path)
    task = PostgresAgentTaskStore(
        postgres_dsn,
        deployment_namespace=handoff_namespace,
    )
    assert task.active_segment(TaskId(source_id)) == result.child_session_id
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            """
            SELECT operation.status, envelope.artifact_id, dispatch.status
            FROM handoff_operations operation
            JOIN session_handoff_envelopes envelope USING (
                deployment_namespace, handoff_id
            )
            JOIN handoff_dispatch_outbox dispatch USING (
                deployment_namespace, handoff_id
            )
            WHERE operation.deployment_namespace = %s
            """,
            (handoff_namespace,),
        ).fetchone() == ("committed", request.artifact_id, "pending")

    changed = replace(
        request,
        create_request=replace(request.create_request, title="different title"),
    )
    with pytest.raises(HandoffStorageConflictError):
        store.commit(changed)

    replay = store.commit(request)

    assert replay == replace(result, idempotent_replay=True)
    assert replay.idempotent_replay is True


def test_commit_preserves_the_workspace_binding_revision_for_child_recovery(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    workspaces = PostgresWorkspaceProjectionStore(
        postgres_dsn,
        deployment_namespace=handoff_namespace,
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE workspace_projections
            SET runtime_name = 'gvisor', runtime_engine = 'docker',
                runtime_image = %s, runtime_spec_digest = %s,
                runtime_network_enforcement = 'isolated',
                runtime_workspace_writable = true
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (
                "python@sha256:" + "a" * 64,
                "b" * 64,
                handoff_namespace,
                source_id,
            ),
        )
    store = _store(postgres_dsn, handoff_namespace)
    operation, request = _prepared_commit(store, source_id)

    result = store.commit(request)

    child_workspace = workspaces.get_workspace(result.child_session_id)
    assert child_workspace is not None
    assert child_workspace.runtime_name == "gvisor"
    assert child_workspace.runtime_engine == "docker"
    assert child_workspace.runtime_spec_digest == "b" * 64
    assert (
        store.inspect_source_facts(result.child_session_id, at=NOW).workspace_revision
        == request.envelope.workspace_revision
    )


def test_reserve_is_idempotent_and_rejects_a_different_request(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    create_request = _create_request(source_id, idempotency_key="same-key")
    facts = store.inspect_source_facts(source_id, at=NOW)

    first = _reserve(store, create_request, facts=facts, request_hash="1" * 64)
    second = _reserve(store, create_request, facts=facts, request_hash="1" * 64)

    assert second == first
    with pytest.raises(HandoffIdempotencyConflictError):
        _reserve(store, create_request, facts=facts, request_hash="2" * 64)


def test_reserve_rejects_stale_authority_before_operation_write(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    create_request = _create_request(source_id, idempotency_key="stale-authority")
    facts = store.inspect_source_facts(source_id, at=NOW)
    stale = replace(facts, authority_revision="f" * 64)

    with pytest.raises(HandoffStorageConflictError, match="authority facts"):
        _reserve(store, create_request, facts=stale, request_hash=_request_hash(create_request))

    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT count(*) FROM handoff_operations
            WHERE deployment_namespace = %s
            """,
            (handoff_namespace,),
        ).fetchone()
        assert row is not None and row[0] == 0


def test_reserve_rejects_an_active_source_lease_before_operation_write(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    leases = PostgresLeaseStore(postgres_dsn, deployment_namespace=handoff_namespace)
    leases.acquire(source_id, owner_instance_id="handoff-worker", ttl=timedelta(minutes=1))
    store = _store(postgres_dsn, handoff_namespace)
    create_request = _create_request(source_id, idempotency_key="active-lease")
    facts = store.inspect_source_facts(source_id, at=NOW)

    with pytest.raises(HandoffStorageConflictError, match="active lease"):
        _reserve(store, create_request, facts=facts, request_hash=_request_hash(create_request))

    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT count(*) FROM handoff_operations
            WHERE deployment_namespace = %s
            """,
            (handoff_namespace,),
        ).fetchone()
        assert row is not None and row[0] == 0


def test_abort_requires_reservation_identity_and_administrative_cas(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, _ = _prepared_commit(store, source_id)
    authority = AdministrativeMutationCAS(
        deployment_namespace=handoff_namespace,
        session_id=source_id,
        expected_stream_revision=operation.expected_source_stream_version,
    )
    invalid = SessionHandoffAbortRequest(
        operation=replace(operation, request_hash="f" * 64),
        authority=authority,
        code="invalid_request_identity",
    )

    with pytest.raises(HandoffStorageConflictError, match="reservation facts"):
        store.abort_authorized(invalid)
    assert _operation_status(postgres_dsn, handoff_namespace, operation.operation_id) == (
        "preparing",
        None,
    )

    stale_authority = authority.model_copy(
        update={"expected_stream_revision": authority.expected_stream_revision + 1}
    )
    with pytest.raises(HandoffStorageConflictError, match="authority"):
        store.abort_authorized(
            SessionHandoffAbortRequest(
                operation=operation,
                authority=stale_authority,
                code="stale_cas",
            )
        )
    assert _operation_status(postgres_dsn, handoff_namespace, operation.operation_id) == (
        "preparing",
        None,
    )

    request = SessionHandoffAbortRequest(
        operation=operation,
        authority=authority,
        code="validation_rejected",
    )
    aborted = store.abort_authorized(request)
    assert aborted.status.value == "aborted"
    assert aborted.abort_code == request.code
    assert store.abort_authorized(request) == aborted


def _operation_status(dsn: str, namespace: str, operation_id: str) -> tuple[str, str | None]:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT status, abort_code FROM handoff_operations
            WHERE deployment_namespace = %s AND operation_id = %s
            """,
            (namespace, operation_id),
        ).fetchone()
    assert row is not None
    return str(row[0]), row[1]


def test_stale_workspace_facts_leave_no_partial_handoff_rows(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, request = _prepared_commit(store, source_id)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE workspace_projections SET workspace_root = %s
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (str(tmp_path / "drifted"), handoff_namespace, source_id),
        )
    before = _aggregate_counts(postgres_dsn, handoff_namespace)

    with pytest.raises(HandoffStorageConflictError):
        store.commit(request)

    assert _aggregate_counts(postgres_dsn, handoff_namespace) == before
    assert (
        PostgresEventStore(
            postgres_dsn,
            deployment_namespace=handoff_namespace,
        ).list_for_session(operation.target_session_id)
        == []
    )


def test_commit_rejects_request_changed_after_reservation(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, request = _prepared_commit(store, source_id)
    changed = replace(
        request,
        create_request=replace(request.create_request, stage_prompt="different stage"),
    )
    before = _aggregate_counts(postgres_dsn, handoff_namespace)

    with pytest.raises(HandoffStorageConflictError):
        store.commit(changed)

    assert _aggregate_counts(postgres_dsn, handoff_namespace) == before
    assert (
        PostgresEventStore(
            postgres_dsn,
            deployment_namespace=handoff_namespace,
        ).list_for_session(operation.target_session_id)
        == []
    )


def test_late_failure_rolls_back_every_aggregate_write(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, request = _prepared_commit(store, source_id)
    before = _aggregate_counts(postgres_dsn, handoff_namespace)
    original = handoff_transactions._insert_envelope_and_dispatch

    def fail_after_outbox(
        connection: Any,
        deployment_namespace: str,
        current: HandoffOperation,
        commit_request: SessionHandoffCommitRequest,
    ) -> None:
        original(connection, deployment_namespace, current, commit_request)
        raise RuntimeError("injected after outbox")

    monkeypatch.setattr(
        handoff_transactions,
        "_insert_envelope_and_dispatch",
        fail_after_outbox,
    )

    with pytest.raises(RuntimeError, match="injected after outbox"):
        store.commit(request)

    assert _aggregate_counts(postgres_dsn, handoff_namespace) == before
    assert (
        len(
            PostgresEventStore(
                postgres_dsn,
                deployment_namespace=handoff_namespace,
            ).list_for_session(source_id)
        )
        == 5
    )
    assert (
        PostgresProjectionStore(
            postgres_dsn,
            deployment_namespace=handoff_namespace,
        ).get_session(operation.target_session_id)
        is None
    )
    assert (
        PostgresAgentTaskStore(
            postgres_dsn,
            deployment_namespace=handoff_namespace,
        ).active_segment(TaskId(source_id))
        == source_id
    )


def test_committed_envelope_rejects_database_update_and_delete(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, request = _prepared_commit(store, source_id)
    store.commit(request)

    with pytest.raises(psycopg.Error, match="immutable"):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                """
                UPDATE session_handoff_envelopes SET checksum = %s
                WHERE deployment_namespace = %s AND handoff_id = %s
                """,
                ("f" * 64, handoff_namespace, operation.handoff_id),
            )
    with pytest.raises(psycopg.Error, match="immutable"):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                """
                DELETE FROM session_handoff_envelopes
                WHERE deployment_namespace = %s AND handoff_id = %s
                """,
                (handoff_namespace, operation.handoff_id),
            )


def test_concurrent_successors_have_exactly_one_winner(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    facts = store.inspect_source_facts(source_id, at=NOW)
    operations = tuple(
        _reserve(
            store,
            _create_request(source_id, idempotency_key=f"winner-{index}"),
            facts=facts,
            request_hash=_request_hash(
                _create_request(source_id, idempotency_key=f"winner-{index}")
            ),
        )
        for index in (1, 2)
    )
    requests = tuple(
        _commit_for_operation(
            operation,
            _create_request(source_id, idempotency_key=f"winner-{index}"),
        )
        for index, operation in zip((1, 2), operations, strict=True)
    )

    def commit(request: SessionHandoffCommitRequest) -> object:
        try:
            return _store(postgres_dsn, handoff_namespace).commit(request)
        except HandoffStorageConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(commit, requests))

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, HandoffStorageConflictError) for result in results) == 1
    counts = _aggregate_counts(postgres_dsn, handoff_namespace)
    assert counts["committed_operations"] == 1
    assert counts["envelopes"] == 1
    assert counts["dispatches"] == 1
    assert counts["child_streams"] == 1
    assert (
        len(
            PostgresAgentTaskStore(
                postgres_dsn,
                deployment_namespace=handoff_namespace,
            ).segments(TaskId(source_id))
        )
        == 2
    )


def _seed_completed_source(
    dsn: str,
    namespace: str,
    workspace_root: Path,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Source stage",
            user_input="Complete source",
            workspace_root=workspace_root,
            policy_profile="local-safe",
            created_at=NOW,
        )
    )
    events = [
        *bootstrap.events,
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    ]
    event_store = PostgresEventStore(dsn, deployment_namespace=namespace)
    for event in events:
        event_store.append(event)
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(
        rebuild_session(events)
    )
    PostgresWorkspaceProjectionStore(dsn, deployment_namespace=namespace).save_workspace(
        rebuild_workspace(events)
    )
    PostgresAgentTaskStore(dsn, deployment_namespace=namespace).ensure_for_session(
        bootstrap.session.session_id
    )
    leases = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    lease = leases.acquire(
        bootstrap.session.session_id,
        owner_instance_id="worker-source",
        ttl=timedelta(minutes=1),
    )
    leases.release(bootstrap.session.session_id, fence=lease.fence)
    return bootstrap.session.session_id


def _prepared_commit(
    store: PostgresSessionHandoffStore,
    source_id: SessionId,
) -> tuple[HandoffOperation, SessionHandoffCommitRequest]:
    create_request = _create_request(source_id, idempotency_key="handoff-key-1")
    facts = store.inspect_source_facts(source_id, at=NOW)
    operation = _reserve(
        store,
        create_request,
        facts=facts,
        request_hash=_request_hash(create_request),
    )
    return operation, _commit_for_operation(operation, create_request)


def _reserve(
    store: PostgresSessionHandoffStore,
    create_request: SessionHandoffCreateRequest,
    *,
    facts: HandoffSourceFacts,
    request_hash: str,
) -> HandoffOperation:
    return store.reserve(
        create_request,
        request_hash=request_hash,
        expected_source_stream_version=facts.stream_version,
        source_lease_fence=facts.lease_fence,
        authority_revision=facts.authority_revision,
        workspace_revision=facts.workspace_revision,
        task_profile_revision=facts.task_profile_revision,
        effective_depth_limit=facts.effective_depth_limit,
    )


def _create_request(
    source_id: SessionId,
    *,
    idempotency_key: str,
) -> SessionHandoffCreateRequest:
    return SessionHandoffCreateRequest(
        source_session_id=source_id,
        idempotency_key=idempotency_key,
        title="Storage stage",
        reason=HandoffReason.OPERATOR_HANDOFF,
        stage_prompt="Start storage implementation",
        principal_identity_hash="principal-hash",
        actor_kind=HandoffActorKind.OPERATOR,
        requested_authority=frozenset({"read"}),
    )


def _commit_for_operation(
    operation: HandoffOperation,
    create_request: SessionHandoffCreateRequest,
) -> SessionHandoffCommitRequest:
    draft = SessionHandoffEnvelope(
        handoff_id=operation.handoff_id,
        source_session_id=operation.source_session_id,
        target_session_id=operation.target_session_id,
        root_session_id=operation.source_session_id,
        source_stage_index=0,
        target_stage_index=1,
        reason=create_request.reason,
        objective=OBJECTIVE,
        protected_user_constraints=("do not widen authority",),
        completed_work=COMPLETED_WORK,
        pending_work=PENDING_WORK,
        immediate_next=create_request.stage_prompt,
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=4),
        source_event_hash="source-event-hash",
        workspace_revision=operation.workspace_revision,
        created_at=NOW,
        checksum="0" * 64,
    )
    envelope = draft.model_copy(update={"checksum": draft.expected_checksum()})
    return SessionHandoffCommitRequest(
        operation=operation,
        create_request=create_request,
        envelope=envelope,
        artifact_id=f"handoff-envelope-{operation.handoff_id}",
    )


def _request_hash(request: SessionHandoffCreateRequest) -> str:
    return canonical_handoff_request_hash(
        request,
        objective=OBJECTIVE,
        completed_work=COMPLETED_WORK,
        pending_work=PENDING_WORK,
    )


def _aggregate_counts(dsn: str, namespace: str) -> dict[str, int]:
    with psycopg.connect(dsn) as connection:
        return {
            "committed_operations": _count(
                connection.execute(
                    """
                SELECT count(*) FROM handoff_operations
                WHERE deployment_namespace = %s AND status = 'committed'
                """,
                    (namespace,),
                ).fetchone()
            ),
            "envelopes": _count(
                connection.execute(
                    """
                    SELECT count(*) FROM session_handoff_envelopes
                    WHERE deployment_namespace = %s
                    """,
                    (namespace,),
                ).fetchone()
            ),
            "dispatches": _count(
                connection.execute(
                    "SELECT count(*) FROM handoff_dispatch_outbox WHERE deployment_namespace = %s",
                    (namespace,),
                ).fetchone()
            ),
            "child_streams": _count(
                connection.execute(
                    """
                SELECT count(*) FROM session_streams stream
                WHERE stream.deployment_namespace = %s
                  AND stream.session_id NOT IN (
                    SELECT source_session_id FROM handoff_operations
                    WHERE deployment_namespace = %s
                  )
                """,
                    (namespace, namespace),
                ).fetchone()
            ),
        }


def _count(row: tuple[object, ...] | None) -> int:
    assert row is not None
    value = row[0]
    assert isinstance(value, int)
    return value


def _store(dsn: str, namespace: str) -> PostgresSessionHandoffStore:
    return PostgresSessionHandoffStore(dsn, deployment_namespace=namespace)


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute("SET LOCAL zebra.allow_handoff_envelope_delete = 'on'")
        for table in (
            "handoff_dispatch_outbox",
            "session_handoff_envelopes",
            "handoff_operations",
            "task_event_index",
            "execution_segments",
            "agent_tasks",
            "worker_leases",
            "workspace_projections",
            "session_projections",
            "session_events",
            "session_streams",
            "control_plane_epochs",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )
