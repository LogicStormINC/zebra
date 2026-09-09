"""Real PostgreSQL proof for atomic command and Skill snapshot admission."""

import asyncio
import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.domain.extensions import SkillInstallation, SkillVersion
from agent_core.domain.identifiers import SessionId
from agent_core.ports.extension_snapshots import ExtensionSnapshotNotFoundError
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_security.extension_authority import extension_runtime_scope_from_grant
from agent_storage import apply_postgres_migrations
from agent_storage.live_event_store import PostCommitPublishingEventStore
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from agent_storage.postgres.extensions import (
    ExtensionSnapshotAdmissionConflictError,
    PostgresExtensionStore,
)
from agent_storage.postgres.projections import PostgresProjectionStore
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from psycopg import sql
from psycopg.conninfo import make_conninfo
from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.session_payloads import CreateSessionPayload, parse_create_session_payload
from zebra_agent_api.session_queue import create_queued_session
from zebra_agent_worker.extension_recovery import WorkerExtensionStore, recover_turn_extension

from tests.agent_security.test_extension_authority import _task_binding, _verified
from tests.agent_storage.test_postgres_command_wakeup import (
    NAMESPACE as WAKEUP_NAMESPACE,
)
from tests.agent_storage.test_postgres_command_wakeup import _counts, _enable

NAMESPACE = "extension-turn-admission"


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    value = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not value:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return value


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"extension_turn_admission_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _installation(scope, *, revision: int = 1, enabled: bool = True) -> SkillInstallation:
    return SkillInstallation(
        scope=scope,
        installation_id="installed",
        revision=revision,
        enabled=enabled,
        version=SkillVersion(
            skill_id="skill",
            version_id="v1",
            artifact_ref="artifact://private",
            content_digest="a" * 64,
        ),
    )


def _seed_task(dsn: str, namespace: str, *, skill_components=("skill",)):
    verified = _verified(scopes=["agent.run"])
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="extension",
            user_input="first",
            workspace_root=Path("/tmp"),
            host_context=verified.context,
            skill_components=skill_components,
        )
    )
    binding = _task_binding(verified).model_copy(
        update={"task_id": str(bootstrap.session.session_id)}
    )
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=namespace).admit(
        TaskAdmissionRequest(
            events=bootstrap.events,
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=binding,
        )
    )
    return bootstrap, verified


@pytest.mark.parametrize("kind", ["message", "run", "resume"])
def test_distinct_verified_issuer_and_origin_survive_real_task_admission(
    dsn: str, kind: str
) -> None:
    verified = _verified(
        iss="https://api.trench.example.com",
        origin="https://trench.example.com",
        scopes=["agent.run"],
    )
    parsed = parse_create_session_payload(
        {"title": "Trench", "prompt": "first", "workspace": "/tmp"}
    )
    assert isinstance(parsed, dict)
    created = create_queued_session(
        SimpleNamespace(artifact_payloads=SimpleNamespace()),
        cast(CreateSessionPayload, parsed),
        host_context=verified.context,
        verified_host_grant=verified,
        admission_dsn=dsn,
        admission_namespace=NAMESPACE,
    )
    assert created.status_code == 201
    session_id = str(created.body["session_id"])
    snapshot_store = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshot_store.resolve_task_ceiling(session_id=session_id)
    assert ceiling.binding.host_capability.authority_issuer == verified.authority_issuer
    assert ceiling.binding.host_capability.host_context.origin == verified.context.origin

    events = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    projections = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    session_key = SessionId(UUID(session_id))
    session = projections.get_session(session_key)
    assert session is not None
    publisher = Mock()
    stores = SimpleNamespace(
        events=PostCommitPublishingEventStore(events, publisher), sessions=projections
    )
    admission = CloudExtensionTurnAdmission(
        PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE),
        snapshot_store,
        snapshot_store,
    )
    request = {
        "kind": kind,
        "expected_revision": session.current_sequence,
        "payload": {"content": "follow up"},
    }
    forged = submit_session_command(
        stores,
        session_id,
        request,
        idempotency_key="forged-issuer",
        extension_admission=admission,
        verified_host_grant=replace(verified, authority_issuer="https://forged.example.com"),
    )
    assert forged.status_code == 403

    accepted = submit_session_command(
        stores,
        session_id,
        request,
        idempotency_key="valid-issuer",
        extension_admission=admission,
        verified_host_grant=verified,
    )
    assert accepted.status_code == 202
    event = events.list_for_session(session_key)[-1]
    publisher.publish_committed.assert_called_once_with(event)
    snapshot = asyncio.run(
        snapshot_store.get(
            scope=extension_runtime_scope_from_grant(verified),
            session_id=session_id,
            turn_id=event.payload["extension_turn_id"],
            expected_digest=event.payload["extension_snapshot_digest"],
        )
    )
    assert snapshot.scope.authority_issuer == "https://api.trench.example.com"
    assert snapshot.scope.workspace_id == verified.context.workspace_ref


def _accepted(
    snapshot: ExtensionSnapshot,
    *,
    expected_revision: int = 0,
    sequence: int = 0,
    key: str = "message",
) -> SessionEvent:
    from uuid import UUID

    from agent_core.contracts import SessionCommand, SessionCommandKind
    from agent_core.domain.identifiers import SessionId

    command = SessionCommand(
        session_id=SessionId(UUID(snapshot.session_id)),
        kind=SessionCommandKind.MESSAGE,
        expected_revision=expected_revision,
        idempotency_key=key,
        payload={"content": "go"},
    )
    return SessionEvent.create(
        session_id=command.session_id,
        sequence=sequence,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(
            extension_snapshot_digest=snapshot.digest,
            extension_turn_id=snapshot.turn_id,
        ),
        idempotency_key=command.idempotency_key,
    )


def test_event_wakeup_and_snapshot_commit_or_roll_back_together(dsn: str) -> None:
    bootstrap, verified = _seed_task(dsn, WAKEUP_NAMESPACE)
    session = bootstrap.session
    _enable(dsn)
    scope = extension_runtime_scope_from_grant(verified)
    installation = _installation(scope)
    asyncio.run(
        PostgresExtensionStore(dsn, deployment_namespace=WAKEUP_NAMESPACE).save_skill(
            scope=scope,
            installation=installation,
            expected_revision=None,
        )
    )
    session_id = str(session.session_id)
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id=session_id,
        turn_id=str(uuid4()),
        skills=(installation,),
    )
    event = _accepted(
        snapshot,
        expected_revision=session.current_sequence,
        sequence=session.current_sequence + 1,
    )
    events = PostgresEventStore(dsn, deployment_namespace=WAKEUP_NAMESPACE)
    snapshots = PostgresExtensionSnapshotStore(dsn, deployment_namespace=WAKEUP_NAMESPACE)
    task_ceiling = snapshots.resolve_task_ceiling(session_id=session_id)

    events.append_with_extension_snapshot(
        event, scope=scope, snapshot=snapshot, task_ceiling=task_ceiling
    )
    restored = asyncio.run(
        PostgresExtensionSnapshotStore(
            dsn,
            deployment_namespace=WAKEUP_NAMESPACE,
        ).get(
            scope=scope,
            session_id=session_id,
            turn_id=snapshot.turn_id,
            expected_digest=snapshot.digest,
        )
    )
    assert restored == snapshot
    assert (
        events.list_for_session(event.session_id)[-1].payload["extension_snapshot_digest"]
        == snapshot.digest
    )
    assert _counts(dsn) == (1, 1)

    other = snapshot.model_copy(update={"turn_id": str(uuid4())})
    rejected = _accepted(
        other,
        expected_revision=session.current_sequence + 1,
        sequence=session.current_sequence + 2,
        key="rejected-message",
    )
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL(
                "ALTER TABLE turn_extension_snapshots ADD CONSTRAINT reject_snapshot "
                "CHECK (snapshot_digest <> {})"
            ).format(sql.Literal(other.digest))
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        events.append_with_extension_snapshot(
            rejected, scope=scope, snapshot=other, task_ceiling=task_ceiling
        )
    assert events.list_for_session(rejected.session_id)[-1] == event
    assert _counts(dsn) == (1, 1)
    with pytest.raises(ExtensionSnapshotNotFoundError):
        asyncio.run(
            PostgresExtensionSnapshotStore(
                dsn,
                deployment_namespace=WAKEUP_NAMESPACE,
            ).get(
                scope=scope,
                session_id=other.session_id,
                turn_id=other.turn_id,
                expected_digest=other.digest,
            )
        )


def test_real_duplicate_reuses_original_snapshot_after_disable(dsn: str) -> None:
    bootstrap, verified = _seed_task(dsn, NAMESPACE)
    scope = extension_runtime_scope_from_grant(verified)
    configurations = PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE)
    installation = _installation(scope)
    asyncio.run(
        configurations.save_skill(
            scope=scope,
            installation=installation,
            expected_revision=None,
        )
    )
    event_store = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    projections = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    stores = SimpleNamespace(events=event_store, sessions=projections)
    snapshot_store = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    admission = CloudExtensionTurnAdmission(configurations, snapshot_store, snapshot_store)
    request = {
        "kind": "message",
        "expected_revision": bootstrap.session.current_sequence,
        "payload": {"content": "follow up"},
    }
    first = submit_session_command(
        stores,
        str(bootstrap.session.session_id),
        request,
        idempotency_key="duplicate",
        extension_admission=admission,
        verified_host_grant=verified,
    )
    asyncio.run(
        configurations.save_skill(
            scope=scope,
            installation=_installation(scope, revision=2, enabled=False),
            expected_revision=1,
        )
    )
    second = submit_session_command(
        stores,
        str(bootstrap.session.session_id),
        request,
        idempotency_key="duplicate",
        extension_admission=admission,
        verified_host_grant=verified,
    )
    assert first.status_code == 202
    assert second.status_code == 200 and second.body["status"] == "duplicate"
    accepted = event_store.list_for_session(bootstrap.session.session_id)[-1]
    snapshot = asyncio.run(
        PostgresExtensionSnapshotStore(
            dsn,
            deployment_namespace=NAMESPACE,
        ).get(
            scope=scope,
            session_id=str(bootstrap.session.session_id),
            turn_id=accepted.payload["extension_turn_id"],
            expected_digest=accepted.payload["extension_snapshot_digest"],
        )
    )
    assert snapshot.skills == (installation,)


def test_existing_turn_snapshot_remains_admissible_after_live_disable(dsn: str) -> None:
    bootstrap, verified = _seed_task(dsn, NAMESPACE)
    scope = extension_runtime_scope_from_grant(verified)
    configurations = PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE)
    installation = _installation(scope)
    asyncio.run(
        configurations.save_skill(scope=scope, installation=installation, expected_revision=None)
    )
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id=str(bootstrap.session.session_id),
        turn_id=str(uuid4()),
        skills=(installation,),
    )
    events = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    snapshot_store = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshot_store.resolve_task_ceiling(session_id=snapshot.session_id)
    first = _accepted(
        snapshot,
        expected_revision=bootstrap.session.current_sequence,
        sequence=bootstrap.session.current_sequence + 1,
        key="first-clarification",
    )
    events.append_with_extension_snapshot(
        first, scope=scope, snapshot=snapshot, task_ceiling=ceiling
    )
    asyncio.run(
        configurations.save_skill(
            scope=scope,
            installation=_installation(scope, revision=2, enabled=False),
            expected_revision=1,
        )
    )
    second = _accepted(
        snapshot,
        expected_revision=first.sequence,
        sequence=first.sequence + 1,
        key="second-clarification",
    )
    assert (
        events.append_with_extension_snapshot(
            second, scope=scope, snapshot=snapshot, task_ceiling=ceiling
        )
        == second
    )


def test_internal_segment_resolves_root_task_skill_ceiling(dsn: str) -> None:
    bootstrap, _ = _seed_task(dsn, NAMESPACE, skill_components=("skill", "other"))
    root_id = bootstrap.session.session_id
    internal_id = uuid4()
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO session_streams VALUES (%s, %s, 0)",
            (NAMESPACE, internal_id),
        )
        connection.execute(
            """
            INSERT INTO session_projections (
                deployment_namespace, session_id, title, status, created_at,
                updated_at, current_sequence, approval_context_json,
                clarification_context_json, task_plan_json
            )
            SELECT deployment_namespace, %s, title, status, created_at, updated_at,
                   0, NULL, NULL, NULL
            FROM session_projections
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (internal_id, NAMESPACE, root_id),
        )
        connection.execute(
            """
            INSERT INTO execution_segments (
                deployment_namespace, session_id, task_id, predecessor_id,
                segment_index, visibility, rollover_reason
            ) VALUES (%s, %s, %s, %s, 1, 'internal', 'context_pressure')
            """,
            (NAMESPACE, internal_id, root_id, root_id),
        )
    ceiling = PostgresExtensionSnapshotStore(
        dsn, deployment_namespace=NAMESPACE
    ).resolve_task_ceiling(session_id=str(internal_id))
    assert ceiling.task_id == str(root_id)
    assert ceiling.skill_components == ("other", "skill")


def test_revision_drift_leaves_neither_event_nor_snapshot(dsn: str) -> None:
    bootstrap, verified = _seed_task(dsn, NAMESPACE)
    scope = extension_runtime_scope_from_grant(verified)
    configurations = PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE)
    original = _installation(scope)
    asyncio.run(
        configurations.save_skill(
            scope=scope,
            installation=original,
            expected_revision=None,
        )
    )
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id=str(bootstrap.session.session_id),
        turn_id=str(uuid4()),
        skills=(original,),
    )
    asyncio.run(
        configurations.save_skill(
            scope=scope,
            installation=_installation(scope, revision=2, enabled=False),
            expected_revision=1,
        )
    )
    events = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    snapshot_store = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshot_store.resolve_task_ceiling(session_id=snapshot.session_id)
    with pytest.raises(ExtensionSnapshotAdmissionConflictError, match="changed during admission"):
        events.append_with_extension_snapshot(
            _accepted(
                snapshot,
                expected_revision=bootstrap.session.current_sequence,
                sequence=bootstrap.session.current_sequence + 1,
            ),
            scope=scope,
            snapshot=snapshot,
            task_ceiling=ceiling,
        )
    assert events.list_for_session(bootstrap.session.session_id) == list(bootstrap.events)
    with pytest.raises(ExtensionSnapshotNotFoundError):
        asyncio.run(
            PostgresExtensionSnapshotStore(
                dsn,
                deployment_namespace=NAMESPACE,
            ).get(
                scope=scope,
                session_id=snapshot.session_id,
                turn_id=snapshot.turn_id,
                expected_digest=snapshot.digest,
            )
        )


def test_concurrent_stream_revision_race_cannot_orphan_losing_snapshot(dsn: str) -> None:
    bootstrap, verified = _seed_task(dsn, NAMESPACE)
    scope = extension_runtime_scope_from_grant(verified)
    installation = _installation(scope)
    asyncio.run(
        PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE).save_skill(
            scope=scope,
            installation=installation,
            expected_revision=None,
        )
    )
    session_id = str(bootstrap.session.session_id)
    snapshots = tuple(
        ExtensionSnapshot(
            scope=scope,
            session_id=session_id,
            turn_id=str(uuid4()),
            skills=(installation,),
        )
        for _ in range(2)
    )
    events = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    snapshot_store = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshot_store.resolve_task_ceiling(session_id=session_id)

    def admit(index: int) -> bool:
        try:
            events.append_with_extension_snapshot(
                _accepted(
                    snapshots[index],
                    expected_revision=bootstrap.session.current_sequence,
                    sequence=bootstrap.session.current_sequence + 1,
                    key=f"race-{index}",
                ),
                scope=scope,
                snapshot=snapshots[index],
                task_ceiling=ceiling,
            )
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(admit, range(2)))
    assert sorted(outcomes) == [False, True]
    canonical = events.list_for_session(bootstrap.session.session_id)
    assert len(canonical) == len(bootstrap.events) + 1
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT snapshot_digest FROM turn_extension_snapshots WHERE deployment_namespace = %s",
            (NAMESPACE,),
        ).fetchall()
    assert rows == [(canonical[-1].payload["extension_snapshot_digest"],)]


def test_worker_restart_recovers_exact_bound_snapshot_from_postgres(dsn: str) -> None:
    bootstrap, verified = _seed_task(dsn, NAMESPACE)
    session_id = bootstrap.session.session_id
    scope = extension_runtime_scope_from_grant(verified)
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id=str(session_id),
        turn_id=str(uuid4()),
        skills=(_installation(scope),),
    )
    store = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    asyncio.run(store.save(scope=scope, snapshot=snapshot))
    accepted = _accepted(snapshot, sequence=1, key="worker-restart")
    materialized = SessionEvent.create(
        session_id=session_id,
        sequence=2,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={
            "content": "go",
            "turn_id": snapshot.turn_id,
            "turn_index": 1,
            "origin": "human",
        },
        idempotency_key="worker-restart:message",
    )

    first = recover_turn_extension(
        store=cast(WorkerExtensionStore, store),
        events=[accepted, materialized],
        session_id=session_id,
        task_binding=store.resolve_task_ceiling(session_id=str(session_id)).binding,
    )
    restarted = recover_turn_extension(
        store=cast(
            WorkerExtensionStore,
            PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE),
        ),
        events=[accepted, materialized],
        session_id=session_id,
        task_binding=store.resolve_task_ceiling(session_id=str(session_id)).binding,
    )

    assert first == restarted
    assert first is not None and first.snapshot == snapshot
