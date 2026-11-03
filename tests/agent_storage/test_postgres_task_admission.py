"""Atomic Task admission tests against real PostgreSQL (v25)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import (
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.task_admission import (
    PostgresTaskAdmissionTransaction,
    load_task_binding,
    save_task_binding,
    save_task_binding_in_transaction,
)
from psycopg import connect
from psycopg.rows import dict_row


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"admission-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


def _request(
    *,
    binding: TaskBindingSnapshot | None = None,
    idempotency: IdempotencyRecord | None = None,
) -> TaskAdmissionRequest:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Admission test",
            user_input="hello",
            workspace_root="/tmp/admission-test",
        )
    )
    workspace = rebuild_workspace(list(bootstrap.events))
    return TaskAdmissionRequest(
        events=tuple(bootstrap.events),
        session=bootstrap.session,
        workspace=workspace,
        binding=binding,
        idempotency=idempotency,
    )


def _binding(task_id: str) -> TaskBindingSnapshot:
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/default@1",
        capabilities=capability_set(["evidence.read"]),
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-a",
        authority_issuer="https://host-a.example.com",
        namespace_id="tenant-a",
        grant_digest="c" * 64,
        connector_id="host-a-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=capability_set(["evidence.read"]),
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=task_id,
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=capability_set(["evidence.read"]),
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


def _receipt(dsn: str, namespace: str, key: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        action="task.admission.test",
        idempotency_key=key,
        request_hash="r" * 64,
        status_code=201,
        response_body={"task": key},
        created_at=datetime.now(UTC),
    )


def _count(dsn: str, namespace: str, table: str, column: str, value: str) -> int:
    with connect(dsn) as connection:
        row = connection.execute(
            f"SELECT count(*) FROM {table} WHERE deployment_namespace = %s AND {column} = %s",
            (namespace, value),
        ).fetchone()
    return int(row[0])


def test_admission_persists_every_object_atomically(namespace: str, postgres_dsn: str) -> None:
    transaction = PostgresTaskAdmissionTransaction(postgres_dsn, deployment_namespace=namespace)
    request = _request()
    receipt = transaction.admit(request)
    session_id = str(receipt.session_id)
    assert receipt.event_count == len(request.events)
    assert _count(postgres_dsn, namespace, "session_events", "session_id", session_id) == len(
        request.events
    )
    assert _count(postgres_dsn, namespace, "session_projections", "session_id", session_id) == 1
    assert _count(postgres_dsn, namespace, "agent_tasks", "task_id", str(receipt.task_id)) == 1


def test_admission_with_binding_persists_snapshot(namespace: str, postgres_dsn: str) -> None:
    transaction = PostgresTaskAdmissionTransaction(postgres_dsn, deployment_namespace=namespace)
    request = _request()
    binding = _binding(str(request.events[0].session_id))
    receipt = transaction.admit(
        TaskAdmissionRequest(
            events=request.events,
            session=request.session,
            workspace=request.workspace,
            binding=binding,
        )
    )
    assert receipt.binding_digest == binding.binding_digest
    assert (
        _count(
            postgres_dsn,
            namespace,
            "task_binding_snapshots",
            "task_id",
            str(receipt.task_id),
        )
        == 1
    )


def test_task_binding_renewal_appends_one_locked_revision(
    namespace: str, postgres_dsn: str
) -> None:
    request = _request()
    task_id = TaskId(request.events[0].session_id)
    binding = _binding(str(task_id))
    PostgresTaskAdmissionTransaction(postgres_dsn, deployment_namespace=namespace).admit(
        TaskAdmissionRequest(
            events=request.events,
            session=request.session,
            workspace=request.workspace,
            binding=binding,
        )
    )
    current = load_task_binding(
        postgres_dsn,
        deployment_namespace=namespace,
        task_id=task_id,
    )
    assert current is not None
    renewed = current.model_copy(
        update={
            "host_capability": current.host_capability.model_copy(
                update={"grant_digest": "9" * 64}
            ),
            "binding_revision": 2,
        }
    )

    with connect(postgres_dsn, row_factory=dict_row) as connection:
        save_task_binding_in_transaction(
            connection, namespace, renewed, expected_previous_revision=1
        )
        connection.rollback()
    assert (
        load_task_binding(postgres_dsn, deployment_namespace=namespace, task_id=task_id) == current
    )

    save_task_binding(
        postgres_dsn,
        deployment_namespace=namespace,
        binding=renewed,
        expected_previous_revision=1,
    )

    latest = load_task_binding(
        postgres_dsn,
        deployment_namespace=namespace,
        task_id=task_id,
    )
    assert latest is not None and latest.binding_revision == 2
    assert (
        load_task_binding(
            postgres_dsn, deployment_namespace=namespace, task_id=task_id, binding_revision=1
        )
        == current
    )
    assert (
        load_task_binding(
            postgres_dsn, deployment_namespace=namespace, task_id=task_id, binding_revision=3
        )
        is None
    )
    with pytest.raises(ValueError, match="advanced concurrently"):
        save_task_binding(
            postgres_dsn,
            deployment_namespace=namespace,
            binding=renewed.model_copy(update={"binding_revision": 3}),
            expected_previous_revision=1,
        )

    with connect(postgres_dsn) as connection:
        connection.execute(
            """UPDATE task_binding_snapshots SET binding_digest = %s
               WHERE deployment_namespace = %s AND task_id = %s AND binding_revision = 1""",
            ("0" * 64, namespace, task_id),
        )
    with pytest.raises(ValueError, match="metadata does not match"):
        load_task_binding(
            postgres_dsn, deployment_namespace=namespace, task_id=task_id, binding_revision=1
        )


def test_text_message_commits_event_and_projection_together(namespace, postgres_dsn):
    from dataclasses import replace

    from agent_core.application import SessionMessageAppendCommand, SessionMessageAppendService
    from agent_core.domain.bundle_definition import BundleDefinitionSnapshot
    from agent_storage.event_rows import SessionEventSequenceConflictError
    from agent_storage.postgres.input_artifact_admission import append_input_message

    from tests.agent_core.test_bundle_definition import NOW, bundle_version

    request = _request()
    task_id = TaskId(request.session.session_id)
    binding = _binding(str(task_id))
    request = replace(request, binding=binding)
    version = bundle_version()
    snapshot = BundleDefinitionSnapshot.from_version(version=version, resolved_at=NOW)
    switched = binding.model_copy(
        update={
            "binding_revision": 2,
            "agent_capability_ceiling": binding.agent_capability_ceiling.model_copy(
                update={
                    "definition_snapshot_digest": snapshot.snapshot_digest,
                }
            ),
        }
    )
    PostgresTaskAdmissionTransaction(postgres_dsn, deployment_namespace=namespace).admit(request)
    session = request.session
    event = SessionMessageAppendService().build_event(
        session=session,
        next_sequence=session.current_sequence + 1,
        command=SessionMessageAppendCommand(
            content="follow up",
            prior_human_turns=1,
            definition_snapshot=snapshot,
            selected_model_pin=version.runtime_assembly.provider_profile.pin,
        ),
    )
    with pytest.raises(SessionEventSequenceConflictError, match="effective release changed"):
        append_input_message(
            postgres_dsn,
            namespace,
            session,
            (event,),
            (),
            release_binding=switched,
            effective_release=snapshot,
        )
    assert (
        load_task_binding(postgres_dsn, deployment_namespace=namespace, task_id=task_id) == binding
    )
    from agent_core.contracts.session_commands import (
        MessageReleaseBinding,
        SessionCommand,
        SessionCommandKind,
    )
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_storage.postgres.events import PostgresEventStore

    command = SessionCommand(
        session_id=session.session_id,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=session.current_sequence,
        idempotency_key="switch-release",
        payload={"content": "follow up"},
    )
    accepted = SessionEvent.create(
        session_id=session.session_id,
        sequence=event.sequence,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(
            message_release_binding=MessageReleaseBinding(
                previous_snapshot_digest=binding.agent_capability_ceiling.definition_snapshot_digest,
                snapshot=snapshot,
                binding=switched,
            ),
        ),
        idempotency_key=command.idempotency_key,
    )
    event_store = PostgresEventStore(postgres_dsn, deployment_namespace=namespace)
    with pytest.raises(SessionEventSequenceConflictError, match="effective release changed"):
        event_store.append(accepted)
    assert event_store.list_for_session(session.session_id)[-1].sequence == session.current_sequence
    updated = append_input_message(
        postgres_dsn, namespace, session, (event,), (), release_binding=switched
    )
    assert (
        load_task_binding(postgres_dsn, deployment_namespace=namespace, task_id=task_id) == switched
    )
    assert updated.current_sequence == event.sequence
    with pytest.raises(SessionEventSequenceConflictError):
        append_input_message(postgres_dsn, namespace, session, (event,), ())

    with connect(postgres_dsn) as connection:
        for table in ("session_projections", "workspace_projections"):
            result = connection.execute(
                f"SELECT current_sequence FROM {table} "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (namespace, session.session_id),
            ).fetchone()
            assert result == (event.sequence,)

    from agent_core.domain.agent_definitions import AgentDefinition, AgentRelease
    from agent_storage.postgres.agent_registry import PostgresAgentRegistry

    registry = PostgresAgentRegistry(postgres_dsn, deployment_namespace=namespace)
    registry.save_definition(
        AgentDefinition(
            definition_id=version.definition_id,
            authority_issuer=version.authority_issuer,
            namespace_id=version.namespace_id,
            name="release fence fixture",
            created_at=NOW,
        )
    )
    registry.save_version(version)
    release = registry.append_release(
        AgentRelease.from_version(
            version,
            release_id=uuid4(),
            environment=version.runtime_assembly.bundle.manifest.scope.environment,
            actor_ref="fixture",
            effective_at=NOW,
        )
    )
    published = BundleDefinitionSnapshot.from_release(
        release=release, version=version, resolved_at=NOW
    )
    next_binding = switched.model_copy(
        update={
            "binding_revision": 3,
            "agent_capability_ceiling": switched.agent_capability_ceiling.model_copy(
                update={"definition_snapshot_digest": published.snapshot_digest}
            ),
        }
    )
    from agent_core.application import project_turns
    from agent_storage.postgres.command_wakeup_message import append_command_message
    from agent_storage.postgres.leases import lock_session_lease_boundary

    closed = event
    for turn in project_turns(event_store.list_for_session(session.session_id)):
        closed = event_store.append(
            SessionEvent.create(
                session_id=session.session_id,
                sequence=closed.sequence + 1,
                event_type=EventType.TURN_COMPLETED,
                actor=EventActor.HARNESS,
                payload={"turn_id": turn.turn_id, "turn_index": turn.turn_index},
            )
        )
    next_command = command.model_copy(update={"expected_revision": closed.sequence})
    accepted = SessionEvent.create(
        session_id=session.session_id,
        sequence=closed.sequence + 1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=next_command.event_payload(
            message_release_binding=MessageReleaseBinding(
                previous_snapshot_digest=snapshot.snapshot_digest,
                snapshot=published,
                binding=next_binding,
            ),
        ),
        idempotency_key=next_command.idempotency_key,
    )
    event_store.append(accepted)
    persisted = event_store.list_for_session(session.session_id)[-1]
    assert persisted.payload["message_release_binding"]["snapshot"] == published.model_dump(
        mode="json"
    )

    with connect(postgres_dsn, row_factory=dict_row) as connection:
        lock_session_lease_boundary(connection, namespace, session.session_id)
        message = append_command_message(connection, namespace, persisted, input_event_id=None)
    assert message.payload["definition_snapshot"] == published.model_dump(mode="json")
    assert message.payload["selected_model_pin"] == (
        version.runtime_assembly.provider_profile.pin.model_dump(mode="json")
    )
    assert (
        load_task_binding(postgres_dsn, deployment_namespace=namespace, task_id=task_id)
        == next_binding
    )
    with connect(postgres_dsn, row_factory=dict_row) as connection:
        lock_session_lease_boundary(connection, namespace, session.session_id)
        replayed = append_command_message(
            connection, namespace, persisted, input_event_id=message.event_id
        )
    assert replayed == message
    assert event_store.list_for_session(session.session_id)[-1] == message


def test_idempotent_replay_short_circuits(namespace: str, postgres_dsn: str) -> None:
    transaction = PostgresTaskAdmissionTransaction(postgres_dsn, deployment_namespace=namespace)
    key = f"key-{uuid4()}"
    receipt_record = _receipt(postgres_dsn, namespace, str(key))
    base = _request()
    first = transaction.admit(
        TaskAdmissionRequest(
            events=base.events,
            session=base.session,
            workspace=base.workspace,
            idempotency=receipt_record,
        )
    )
    assert not first.idempotent_replay
    replay = transaction.admit(_request(idempotency=receipt_record))
    assert replay.idempotent_replay
    assert replay.event_count == 0
    assert _count(
        postgres_dsn, namespace, "session_events", "session_id", str(first.session_id)
    ) == len(base.events)
    assert (
        _count(postgres_dsn, namespace, "session_events", "session_id", str(replay.session_id)) == 0
    )


def test_injected_failure_leaves_no_partial_task(namespace: str, postgres_dsn: str) -> None:
    transaction = PostgresTaskAdmissionTransaction(postgres_dsn, deployment_namespace=namespace)
    # first, one fully admitted Task with a binding at revision 1
    established = _request()
    established_task = str(established.events[0].session_id)
    transaction.admit(
        TaskAdmissionRequest(
            events=established.events,
            session=established.session,
            workspace=established.workspace,
            binding=_binding(established_task),
        )
    )
    # second admission: fresh Session/Events (all inserts succeed), but its
    # binding reuses the first task_id at the same revision — the LAST insert
    # violates the task_binding_snapshots primary key mid-transaction
    fresh = _request()
    colliding_binding = _binding(established_task)
    try:
        transaction.admit(
            TaskAdmissionRequest(
                events=fresh.events,
                session=fresh.session,
                workspace=fresh.workspace,
                binding=colliding_binding,
            )
        )
    except Exception:
        pass
    else:
        raise AssertionError("colliding binding must fail the admission mid-transaction")
    fresh_session = str(fresh.events[0].session_id)
    assert _count(postgres_dsn, namespace, "session_events", "session_id", fresh_session) == 0
    assert _count(postgres_dsn, namespace, "session_projections", "session_id", fresh_session) == 0
    assert (
        _count(postgres_dsn, namespace, "task_binding_snapshots", "task_id", established_task) == 1
    )
    assert _count(postgres_dsn, namespace, "session_events", "session_id", established_task) == len(
        established.events
    )


def test_migration_v25_table_exists(postgres_dsn: str) -> None:
    with connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_name = 'task_binding_snapshots' AND table_schema = current_schema()
            """
        ).fetchone()
    assert int(row[0]) == 1


def test_request_validation_rejects_mismatched_binding() -> None:
    request = _request()
    foreign = _binding(str(uuid4()))
    with pytest.raises(ValueError, match="binding must reference"):
        TaskAdmissionRequest(
            events=request.events,
            session=request.session,
            workspace=request.workspace,
            binding=foreign,
        ).validate()
