import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.session_handoff import (
    HandoffActorKind,
    HandoffReason,
    SessionHandoffEnvelope,
)
from agent_core.ports.session_handoff import (
    HandoffOperation,
    SessionHandoffCommitRequest,
    SessionHandoffCreateRequest,
)
from agent_storage import (
    HandoffIdempotencyConflictError,
    HandoffStorageConflictError,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteSessionHandoffStore,
    SQLiteWorkspaceProjectionStore,
    sqlite_control_plane_stores,
)
from zebra_agent_worker.session_handoff import (
    HandoffWorkspaceDriftError,
    SessionHandoffRecoveryGate,
)

NOW = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)


def _recovery_gate(database_path: Path) -> tuple[SessionHandoffRecoveryGate, SQLiteLeaseStore]:
    leases = SQLiteLeaseStore(database_path, clock=lambda: NOW)
    stores = replace(sqlite_control_plane_stores(database_path), leases=leases)
    return SessionHandoffRecoveryGate(str(database_path), stores=stores), leases


def test_commit_atomically_creates_child_events_lineage_envelope_and_outbox(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "handoff.db"
    source_id = _seed_completed_source(database_path, tmp_path)
    store = SQLiteSessionHandoffStore(database_path)
    operation, commit = _prepared_commit(store, source_id)

    result = store.commit(commit)

    assert result.child_session_id == operation.target_session_id
    assert result.child_status == "ready"
    assert result.idempotent_replay is False
    assert store.get_envelope(operation.handoff_id) == commit.envelope
    lineage = store.get_lineage(operation.target_session_id)
    assert [item.session_id for item in lineage] == [source_id, operation.target_session_id]

    source_events = SQLiteEventStore(database_path).list_for_session(source_id)
    child_events = SQLiteEventStore(database_path).list_for_session(operation.target_session_id)
    assert source_events[-1].event_type is EventType.SESSION_HANDOFF_COMMITTED
    assert [event.event_type for event in child_events] == [
        EventType.SESSION_CREATED,
        EventType.SESSION_HANDOFF_RECEIVED,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
    ]
    received_payload = child_events[2].payload
    assert received_payload is not None
    assert received_payload["actor_kind"] == "operator"
    assert received_payload["content"] == "Start storage implementation"
    child_session = SQLiteProjectionStore(database_path).get_session(operation.target_session_id)
    assert child_session is not None
    assert child_session.status.value == "ready"
    child_workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(
        operation.target_session_id
    )
    assert child_workspace is not None
    assert child_workspace.workspace_root == str(tmp_path)

    dispatch = store.claim_dispatch(worker_id="worker-1", claimed_at=NOW)
    assert dispatch is not None
    assert dispatch.child_session_id == operation.target_session_id
    store.acknowledge_dispatch(dispatch.delivery_id, worker_id="worker-1")
    assert store.claim_dispatch(worker_id="worker-2", claimed_at=NOW) is None


def test_child_recovery_revalidates_workspace_even_after_dispatch_ack(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source = _seed_completed_source(database_path, tmp_path)
    handoffs = SQLiteSessionHandoffStore(database_path)
    operation, request = _prepared_commit(handoffs, source)
    handoffs.commit(request)
    gate, leases = _recovery_gate(database_path)
    first_lease = leases.acquire(
        operation.target_session_id, owner_instance_id="worker-1", ttl=timedelta(minutes=1)
    )

    recovered = gate.recover(
        operation.target_session_id,
        fence=first_lease.fence,
        recovered_at=NOW,
    )
    assert recovered is not None
    metadata = recovered.runtime_evidence.metadata
    assert metadata is not None
    assert metadata["trust"] == "untrusted_handoff_evidence"

    workspaces = SQLiteWorkspaceProjectionStore(database_path)
    workspace = workspaces.get_workspace(operation.target_session_id)
    assert workspace is not None
    workspaces.save_workspace(
        workspace.model_copy(update={"workspace_root": str(tmp_path / "drifted")})
    )
    leases.release(operation.target_session_id, fence=first_lease.fence)
    second_lease = leases.acquire(
        operation.target_session_id, owner_instance_id="worker-2", ttl=timedelta(minutes=1)
    )

    with pytest.raises(HandoffWorkspaceDriftError):
        gate.recover(
            operation.target_session_id,
            fence=second_lease.fence,
            recovered_at=NOW + timedelta(seconds=1),
        )

    session = SQLiteProjectionStore(database_path).get_session(operation.target_session_id)
    workspace = workspaces.get_workspace(operation.target_session_id)
    assert session is not None and session.status.value == "suspended"
    assert workspace is not None and workspace.status.value == "suspended"


def test_child_continuation_does_not_reapply_the_initial_workspace_revision(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "handoff.db"
    source = _seed_completed_source(database_path, tmp_path)
    handoffs = SQLiteSessionHandoffStore(database_path)
    operation, request = _prepared_commit(handoffs, source)
    handoffs.commit(request)
    gate, leases = _recovery_gate(database_path)
    first_lease = leases.acquire(
        operation.target_session_id, owner_instance_id="worker-1", ttl=timedelta(minutes=1)
    )

    first = gate.recover(
        operation.target_session_id,
        fence=first_lease.fence,
        recovered_at=NOW,
    )
    assert first is not None
    session_store = SQLiteProjectionStore(database_path)
    session = session_store.get_session(operation.target_session_id)
    assert session is not None
    started = SessionEvent.create(
        session_id=operation.target_session_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        created_at=NOW,
    )
    SQLiteEventStore(database_path).append(started)
    session_store.save_session(apply_event(session, started))

    workspaces = SQLiteWorkspaceProjectionStore(database_path)
    workspace = workspaces.get_workspace(operation.target_session_id)
    assert workspace is not None
    workspaces.save_workspace(workspace.model_copy(update={"runtime_name": "os-sandbox"}))
    leases.release(operation.target_session_id, fence=first_lease.fence)
    second_lease = leases.acquire(
        operation.target_session_id, owner_instance_id="worker-2", ttl=timedelta(minutes=1)
    )

    resumed = gate.recover(
        operation.target_session_id,
        fence=second_lease.fence,
        recovered_at=NOW + timedelta(seconds=1),
    )

    assert resumed == first


def test_child_recovery_rejects_stale_same_owner_lease_generation(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source = _seed_completed_source(database_path, tmp_path)
    handoffs = SQLiteSessionHandoffStore(database_path)
    operation, request = _prepared_commit(handoffs, source)
    handoffs.commit(request)
    gate, leases = _recovery_gate(database_path)
    stale = leases.acquire(
        operation.target_session_id,
        owner_instance_id="worker-1",
        ttl=timedelta(minutes=1),
    )
    leases.release(operation.target_session_id, fence=stale.fence)
    leases.acquire(
        operation.target_session_id,
        owner_instance_id="worker-1",
        ttl=timedelta(minutes=1),
    )

    with pytest.raises(HandoffStorageConflictError, match="current lease"):
        gate.recover(
            operation.target_session_id,
            fence=stale.fence,
            recovered_at=NOW,
        )


def test_reservation_and_commit_retries_return_one_operation_and_child(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source_id = _seed_completed_source(database_path, tmp_path)
    store = SQLiteSessionHandoffStore(database_path)
    operation, commit = _prepared_commit(store, source_id)

    replayed_operation = store.reserve(
        commit.create_request,
        request_hash="request-hash",
        expected_source_stream_version=operation.expected_source_stream_version,
        source_lease_fence=operation.source_lease_fence,
        authority_revision=operation.authority_revision,
        workspace_revision=operation.workspace_revision,
        task_profile_revision=operation.task_profile_revision,
        effective_depth_limit=operation.effective_depth_limit,
    )
    first = store.commit(commit)
    replay = store.commit(commit)

    assert replayed_operation == operation
    assert replay.child_session_id == first.child_session_id
    assert replay.idempotent_replay is True
    assert len(SQLiteEventStore(database_path).list_for_session(source_id)) == 6


def test_same_key_different_request_and_second_successor_fail_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source_id = _seed_completed_source(database_path, tmp_path)
    store = SQLiteSessionHandoffStore(database_path)
    operation, commit = _prepared_commit(store, source_id)
    store.commit(commit)

    with pytest.raises(HandoffIdempotencyConflictError):
        store.reserve(
            commit.create_request,
            request_hash="different-request",
            expected_source_stream_version=operation.expected_source_stream_version,
            source_lease_fence=operation.source_lease_fence,
            authority_revision=operation.authority_revision,
            workspace_revision=operation.workspace_revision,
            task_profile_revision=operation.task_profile_revision,
            effective_depth_limit=operation.effective_depth_limit,
        )

    second_request = replace(commit.create_request, idempotency_key="handoff-key-2")
    facts = store.inspect_source_facts(source_id, at=NOW)
    second_operation = store.reserve(
        second_request,
        request_hash="second-request",
        expected_source_stream_version=facts.stream_version,
        source_lease_fence=facts.lease_fence,
        authority_revision=facts.authority_revision,
        workspace_revision=facts.workspace_revision,
        task_profile_revision=facts.task_profile_revision,
        effective_depth_limit=facts.effective_depth_limit,
    )
    second_commit = _commit_for_operation(second_operation, second_request)
    with pytest.raises(HandoffStorageConflictError, match="successor"):
        store.commit(second_commit)
    assert (
        SQLiteEventStore(database_path).list_for_session(second_operation.target_session_id) == []
    )


def test_source_version_conflict_leaves_no_partial_child(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source_id = _seed_completed_source(database_path, tmp_path)
    store = SQLiteSessionHandoffStore(database_path)
    operation, commit = _prepared_commit(store, source_id)
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=source_id,
            sequence=5,
            event_type=EventType.MEMORY_CANDIDATE_EXTRACTED,
            actor=EventActor.SYSTEM,
            payload={
                "memory_id": "memory-1",
                "memory_type": "fact",
                "status": "candidate",
                "visibility": "session",
                "text": "changed",
                "confidence": 1.0,
                "source_event_start": 4,
                "source_event_end": 4,
            },
            created_at=NOW,
        )
    )

    with pytest.raises(HandoffStorageConflictError, match="reservation facts"):
        store.commit(commit)

    assert store.get_handoff(operation.handoff_id) is None
    assert store.get_envelope(operation.handoff_id) is None
    assert SQLiteEventStore(database_path).list_for_session(operation.target_session_id) == []


def test_active_lease_and_workspace_drift_fail_before_child_mutation(tmp_path: Path) -> None:
    leased_database = tmp_path / "leased.db"
    source_id = _seed_completed_source(leased_database, tmp_path)
    leased_store = SQLiteSessionHandoffStore(leased_database)
    operation, commit = _prepared_commit(leased_store, source_id)
    SQLiteLeaseStore(leased_database, clock=lambda: NOW).acquire(
        source_id,
        owner_instance_id="worker-active",
        ttl=timedelta(minutes=1),
    )
    with pytest.raises(HandoffStorageConflictError, match="active lease"):
        leased_store.commit(commit)
    assert SQLiteEventStore(leased_database).list_for_session(operation.target_session_id) == []

    drift_database = tmp_path / "drift.db"
    drift_source_id = _seed_completed_source(drift_database, tmp_path)
    drift_store = SQLiteSessionHandoffStore(drift_database)
    drift_operation, drift_commit = _prepared_commit(drift_store, drift_source_id)
    workspace_store = SQLiteWorkspaceProjectionStore(drift_database)
    workspace = workspace_store.get_workspace(drift_source_id)
    assert workspace is not None
    workspace_store.save_workspace(
        workspace.model_copy(update={"workspace_root": str(tmp_path / "moved")})
    )
    with pytest.raises(HandoffStorageConflictError, match="reservation facts"):
        drift_store.commit(drift_commit)
    assert (
        SQLiteEventStore(drift_database).list_for_session(drift_operation.target_session_id) == []
    )


def test_handoff_source_fence_is_independent_from_checkpoint(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source_id = _seed_completed_source(database_path, tmp_path)
    current = [NOW]
    leases = SQLiteLeaseStore(database_path, clock=lambda: current[0])
    handoffs = SQLiteSessionHandoffStore(database_path)
    lease = leases.acquire(
        source_id,
        owner_instance_id="worker-a",
        ttl=timedelta(minutes=1),
        checkpoint=3,
    )
    before = handoffs.inspect_source_facts(source_id, at=NOW)
    current[0] += timedelta(seconds=1)

    heartbeat = leases.heartbeat(
        source_id,
        fence=lease.fence,
        ttl=timedelta(minutes=1),
        checkpoint=9,
    )
    after = handoffs.inspect_source_facts(source_id, at=current[0])

    assert before.lease_fence == lease.fence
    assert after.lease_fence == lease.fence
    assert heartbeat.checkpoint == 9
    assert heartbeat.fence.fencing_token != heartbeat.checkpoint


def test_handoff_commit_rejects_generation_change_after_reservation(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source_id = _seed_completed_source(database_path, tmp_path)
    current = [NOW]
    leases = SQLiteLeaseStore(database_path, clock=lambda: current[0])
    first = leases.acquire(
        source_id,
        owner_instance_id="worker-a",
        ttl=timedelta(minutes=1),
    )
    handoffs = SQLiteSessionHandoffStore(database_path)
    operation, commit = _prepared_commit(handoffs, source_id)
    current[0] += timedelta(seconds=1)
    leases.release(source_id, fence=first.fence)
    second = leases.acquire(
        source_id,
        owner_instance_id="worker-b",
        ttl=timedelta(minutes=1),
    )

    assert second.fence.fencing_token == first.fence.fencing_token + 1

    with pytest.raises(HandoffStorageConflictError, match="reservation facts"):
        handoffs.commit(commit)

    assert handoffs.get_envelope(operation.handoff_id) is None
    assert SQLiteEventStore(database_path).list_for_session(operation.target_session_id) == []


def test_legacy_token_only_preparation_is_aborted_on_initialization(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    operation_id = str(uuid4())
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE handoff_operations (
                operation_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                source_session_id TEXT NOT NULL, target_session_id TEXT NOT NULL UNIQUE,
                handoff_id TEXT NOT NULL UNIQUE, idempotency_key_hash TEXT NOT NULL,
                request_hash TEXT NOT NULL, expected_source_stream_version INTEGER NOT NULL,
                source_lease_fencing_token INTEGER, authority_revision TEXT NOT NULL,
                workspace_revision TEXT NOT NULL, task_profile_revision TEXT NOT NULL,
                effective_depth_limit INTEGER NOT NULL, artifact_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, abort_code TEXT,
                UNIQUE(source_session_id, idempotency_key_hash)
            )
            """,
        )
        connection.execute(
            "INSERT INTO handoff_operations VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                operation_id,
                "preparing",
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                "key-hash",
                "request-hash",
                4,
                37,
                "authority",
                "{}",
                "task-profile",
                4,
                None,
                NOW.isoformat(),
                NOW.isoformat(),
                None,
            ),
        )

    SQLiteSessionHandoffStore(database_path)
    with sqlite3.connect(database_path) as connection:
        migrated = connection.execute(
            """
            SELECT status, abort_code, source_lease_epoch,
                   source_lease_owner_instance_id
            FROM handoff_operations WHERE operation_id = ?
            """,
            (operation_id,),
        ).fetchone()

    assert migrated == ("aborted", "legacy_lease_fence_incomplete", None, None)


def test_partial_handoff_fence_is_aborted_on_initialization(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    operation_id = str(uuid4())
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE handoff_operations (
                operation_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                source_session_id TEXT NOT NULL, target_session_id TEXT NOT NULL UNIQUE,
                handoff_id TEXT NOT NULL UNIQUE, idempotency_key_hash TEXT NOT NULL,
                request_hash TEXT NOT NULL, expected_source_stream_version INTEGER NOT NULL,
                source_lease_fencing_token INTEGER, source_lease_epoch TEXT,
                source_lease_owner_instance_id TEXT, authority_revision TEXT NOT NULL,
                workspace_revision TEXT NOT NULL, task_profile_revision TEXT NOT NULL,
                effective_depth_limit INTEGER NOT NULL, artifact_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, abort_code TEXT,
                UNIQUE(source_session_id, idempotency_key_hash)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO handoff_operations (
                operation_id, status, source_session_id, target_session_id,
                handoff_id, idempotency_key_hash, request_hash,
                expected_source_stream_version, source_lease_epoch,
                authority_revision, workspace_revision, task_profile_revision,
                effective_depth_limit, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                "preparing",
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                "key-hash",
                "request-hash",
                4,
                str(uuid4()),
                "authority",
                "{}",
                "task-profile",
                4,
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )

    SQLiteSessionHandoffStore(database_path)
    with sqlite3.connect(database_path) as connection:
        migrated = connection.execute(
            "SELECT status, abort_code FROM handoff_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()

    assert migrated == ("aborted", "legacy_lease_fence_incomplete")


def test_dispatch_lease_can_be_reclaimed_and_lineage_index_rebuilt(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source_id = _seed_completed_source(database_path, tmp_path)
    store = SQLiteSessionHandoffStore(database_path)
    operation, commit = _prepared_commit(store, source_id)
    store.commit(commit)
    first = store.claim_dispatch(worker_id="worker-1", claimed_at=NOW, lease_seconds=10)
    assert first is not None
    assert store.claim_dispatch(worker_id="worker-2", claimed_at=NOW) is None
    reclaimed = store.claim_dispatch(worker_id="worker-2", claimed_at=NOW + timedelta(seconds=11))
    assert reclaimed is not None
    assert reclaimed.delivery_id == first.delivery_id

    assert store.rebuild_lineage_index() == 1
    assert len(store.get_lineage(operation.target_session_id)) == 2


def test_stale_preparing_operations_abort_without_session_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "handoff.db"
    source_id = _seed_completed_source(database_path, tmp_path)
    store = SQLiteSessionHandoffStore(database_path)
    operation, _ = _prepared_commit(store, source_id)

    assert store.abort_stale_preparing(before=operation.created_at + timedelta(seconds=1)) == 1
    aborted = store.abort(operation.operation_id, code="already-stale")
    assert aborted.status.value == "aborted"
    assert len(SQLiteEventStore(database_path).list_for_session(source_id)) == 5


def test_handoff_threads_skill_components_into_child_task_and_authority(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "handoff.db"
    source = _seed_completed_source(database_path, tmp_path)
    handoffs = SQLiteSessionHandoffStore(database_path)
    workspace_store = SQLiteWorkspaceProjectionStore(database_path)
    workspace = workspace_store.get_workspace(source)
    assert workspace is not None

    facts_without = handoffs.inspect_source_facts(source, at=NOW)
    workspace_store.save_workspace(
        workspace.model_copy(update={"skill_components": ("Review", "evidence")})
    )
    facts_with = handoffs.inspect_source_facts(source, at=NOW)
    # skill_components participates in the authority revision hash.
    assert facts_with.authority_revision != facts_without.authority_revision

    operation, request = _prepared_commit(handoffs, source)
    handoffs.commit(request)

    child_events = SQLiteEventStore(database_path).list_for_session(operation.target_session_id)
    prepared = next(event for event in child_events if event.event_type is EventType.TASK_PREPARED)
    # the child TASK_PREPARED payload carries the explicit skill_components section.
    assert prepared.payload["skill_components"] == ["Review", "evidence"]

    child_workspace = workspace_store.get_workspace(operation.target_session_id)
    assert child_workspace is not None
    assert child_workspace.skill_components == ("Review", "evidence")


def _seed_completed_source(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Source stage",
            user_input="Complete source",
            workspace_root=workspace_root,
            policy_profile="local-safe",
            created_at=NOW,
        )
    )
    events = list(bootstrap.events)
    events.extend(
        (
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
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(rebuild_session(events))
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(rebuild_workspace(events))
    return bootstrap.session.session_id


def _prepared_commit(
    store: SQLiteSessionHandoffStore,
    source_id: SessionId,
) -> tuple[HandoffOperation, SessionHandoffCommitRequest]:
    create_request = SessionHandoffCreateRequest(
        source_session_id=source_id,
        idempotency_key="handoff-key-1",
        title="Storage stage",
        reason=HandoffReason.OPERATOR_HANDOFF,
        stage_prompt="Start storage implementation",
        principal_identity_hash="principal-hash",
        actor_kind=HandoffActorKind.OPERATOR,
        requested_authority=frozenset({"read"}),
    )
    facts = store.inspect_source_facts(source_id, at=NOW)
    operation = store.reserve(
        create_request,
        request_hash="request-hash",
        expected_source_stream_version=facts.stream_version,
        source_lease_fence=facts.lease_fence,
        authority_revision=facts.authority_revision,
        workspace_revision=facts.workspace_revision,
        task_profile_revision=facts.task_profile_revision,
        effective_depth_limit=facts.effective_depth_limit,
    )
    return operation, _commit_for_operation(operation, create_request)


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
        objective="Continue the staged task",
        protected_user_constraints=("do not widen authority",),
        completed_work=("source complete",),
        pending_work=("storage",),
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
        artifact_id=f"handoff-artifact-{operation.handoff_id}",
    )
