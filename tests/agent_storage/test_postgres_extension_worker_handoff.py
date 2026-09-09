"""Real RabbitMQ handoff materialization into trusted extension recovery."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import current_turn
from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.application.skill_installations import create_skill_installation
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.skill_publications import publication_identity
from agent_core.domain.tools import ToolCall
from agent_core.domain.turns import InteractionMode, derive_turn_id
from agent_core.ports import ArtifactObjectStorePort
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import publish_skill_package
from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_worker.context_materialization import prepare_worker_context
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.extension_recovery import WorkerExtensionStore, recover_turn_extension
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.worker_skill_catalog import WorkerSkillCatalogSource

from tests.agent_storage import test_skill_publication_minio as publication_fixtures
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup_execution import _setup
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff
from tests.agent_storage.test_postgres_command_wakeup_message import _awaiting, _message, _receipt
from tests.agent_storage.test_postgres_command_wakeup_receipts import (
    _commit,
    _event,
    _refresh,
    _start,
)
from tests.agent_storage.test_postgres_extension_turn_admission import (
    _accepted,
)
from tests.agent_storage.test_postgres_extension_turn_admission import (
    dsn as _dsn_fixture,
)
from tests.agent_storage.test_postgres_extension_turn_admission import (
    postgres_dsn as _pg_fixture,
)
from tests.agent_storage.test_postgres_leases import _expire
from tests.worker.execution.worker_execution_support import _final_response

dsn = _dsn_fixture
postgres_dsn = _pg_fixture
objects = publication_fixtures.objects


def _skill_gateway() -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(), role=MessageRole.ASSISTANT,
                        content="Reading the frozen cloud Skill.", created_at=datetime.now(UTC),
                    ),
                    tool_calls=(ToolCall(
                        tool_call_id=new_tool_call_id(), name="skills.read",
                        arguments={"name": "sample"}, created_at=datetime.now(UTC),
                    ),),
                )
            ),
            _final_response("Cloud Skill read completed."),
        )
    )


@pytest.mark.parametrize("tampered", [False, True])
def test_actual_worker_wires_recovered_skill_tools_and_rejects_object_tamper(
    dsn, tmp_path, monkeypatch, objects, tampered,
) -> None:
    skill_id = publication_identity(
        NAMESPACE,
        ExtensionScope(
            authority_issuer="https://trench.example", namespace_id="tenant-a",
            principal_id="user-a", workspace_id="workspace-a",
        ),
        "sample", "1.0",
    )[0]
    service, stores, first_lease = _setup(
        dsn, tmp_path, monkeypatch, interaction_mode=InteractionMode.CONVERSATION,
        skill_components=(skill_id,), manifest_digest="0" * 64,
    )
    assert (
        service.execute_claimed_session(first_lease).session.status
        is SessionStatus.AWAITING_TURN
    )
    session_id = first_lease.session_id
    scope_store = PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE)
    publications = PostgresSkillPublicationStore(dsn, deployment_namespace=NAMESPACE)

    async def install():
        publication = await publish_skill_package(
            archive=publication_fixtures._archive("PRIVATE-WORKER-SKILL"),
            scope=_scope(PostgresExtensionSnapshotStore(
                dsn, deployment_namespace=NAMESPACE,
            ).resolve_task_ceiling(session_id=str(session_id))),
            deployment_namespace=NAMESPACE, store=publications, objects=objects,
        )
        candidate, _ = await create_skill_installation(
            store=scope_store, scope=publication.scope, idempotency_key="worker-skill",
            payload={"skill_id": publication.version.skill_id,
                     "version_id": publication.version.version_id},
        )
        return await set_extension_enabled(
            store=scope_store, scope=publication.scope, kind="skill",
            object_id=candidate.installation_id, expected_revision=1, enabled=True,
        )

    installed = asyncio.run(install())
    snapshots = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshots.resolve_task_ceiling(session_id=str(session_id))
    turn_id = str(derive_turn_id(session_id, 1))
    snapshot = ExtensionSnapshot(
        scope=installed.scope, session_id=str(session_id), turn_id=turn_id,
        skills=(installed,),
    )
    previous = stores.events.list_for_session(session_id)[-1]
    accepted = _accepted(
        snapshot, expected_revision=previous.sequence,
        sequence=previous.sequence + 1, key=f"worker-skill-{tampered}",
    )
    stores.events.append_with_extension_snapshot(
        accepted, scope=snapshot.scope, snapshot=snapshot, task_ceiling=ceiling,
    )
    handoff = _handoff(dsn, accepted)
    assert handoff.status is HandoffStatus.ACCEPTED and handoff.lease is not None

    class ObjectReader:
        def read_version_verified(self, expectation, object_version):
            payload = objects.read_version_verified(expectation, object_version)
            return payload + b"tampered" if tampered else payload

    service._extension_snapshot_store = snapshots
    service._task_binding_loader = lambda _task_id: ceiling.binding
    service._extension_skills = WorkerSkillCatalogSource(
        scope_store, cast(ArtifactObjectStorePort, ObjectReader()),
    )
    gateway = _skill_gateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway", lambda _settings: gateway,
    )
    result = service.execute_claimed_session(handoff.lease)
    events = stores.events.list_for_session(session_id)
    tools = [event for event in events if event.event_type in {
        EventType.TOOL_EXECUTION_COMPLETED, EventType.TOOL_EXECUTION_FAILED,
    }]
    assert any(tool.name == "skills.read" for tool in gateway.tool_requests[-1])
    if tampered:
        assert tools[-1].event_type is EventType.TOOL_EXECUTION_FAILED
        assert "PRIVATE-WORKER-SKILL" not in str(tools[-1].payload)
    else:
        assert result.session.status is SessionStatus.AWAITING_TURN
        assert tools[-1].event_type is EventType.TOOL_EXECUTION_COMPLETED
        assert "PRIVATE-WORKER-SKILL" in tools[-1].payload["output"]


def _scope(ceiling) -> ExtensionScope:
    host = ceiling.binding.host_capability
    context = host.host_context
    principal = next(
        resource.resource_id
        for resource in context.resource_refs
        if resource.resource_type == "principal"
    )
    return ExtensionScope(
        authority_issuer=host.authority_issuer,
        namespace_id=host.namespace_id,
        principal_id=principal,
        workspace_id=context.workspace_ref,
    )


def _verified_from_ceiling(ceiling) -> VerifiedHostGrant:
    host = ceiling.binding.host_capability
    context = host.host_context
    principal = next(
        resource.resource_id
        for resource in context.resource_refs
        if resource.resource_type == "principal"
    )
    return VerifiedHostGrant(
        context=context,
        grant_id=context.grant_id,
        algorithm=JwtAlgorithm.RS256,
        authority_issuer=host.authority_issuer,
        subject_ref=principal,
    )


def _bound_message(dsn, tmp_path, monkeypatch):
    service, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    snapshots = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshots.resolve_task_ceiling(session_id=str(session_id))
    snapshot = ExtensionSnapshot(
        scope=_scope(ceiling),
        session_id=str(session_id),
        turn_id=str(derive_turn_id(session_id, 1)),
    )
    previous = stores.events.list_for_session(session_id)[-1]
    accepted = _accepted(
        snapshot,
        expected_revision=previous.sequence,
        sequence=previous.sequence + 1,
        key="bound-handoff",
    )
    stores.events.append_with_extension_snapshot(
        accepted, scope=snapshot.scope, snapshot=snapshot, task_ceiling=ceiling
    )
    handed_off = _handoff(dsn, accepted)
    assert handed_off.status is HandoffStatus.ACCEPTED
    return service, stores, handed_off, accepted, snapshot, snapshots, ceiling


def test_bound_handoff_materializes_exact_turn_and_survives_restart(
    dsn, tmp_path, monkeypatch
) -> None:
    _, stores, handed_off, accepted, snapshot, snapshots, ceiling = _bound_message(
        dsn, tmp_path, monkeypatch
    )
    events = stores.events.list_for_session(accepted.session_id)
    message = next(event for event in events if event.causation_id == accepted.event_id)
    assert message.payload["turn_id"] == snapshot.turn_id

    first = recover_turn_extension(
        store=snapshots,
        events=events,
        session_id=accepted.session_id,
        task_binding=ceiling.binding,
    )
    restarted = recover_turn_extension(
        store=PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE),
        events=events,
        session_id=accepted.session_id,
        task_binding=ceiling.binding,
    )
    assert first == restarted and first is not None

    assert handed_off.lease is not None


def test_two_consecutive_bound_handoffs_recover_latest_turn(dsn, tmp_path, monkeypatch) -> None:
    _, stores, first_handoff, first, first_snapshot, snapshots, ceiling = _bound_message(
        dsn, tmp_path, monkeypatch
    )
    _refresh(dsn, first.session_id)
    _start(dsn, first, first_handoff.lease)
    completed = _event(
        dsn,
        first.session_id,
        EventType.TURN_COMPLETED,
        {"turn_id": first_snapshot.turn_id, "turn_index": 1, "closes_segment": False},
    )
    _commit(dsn, completed, first_handoff.lease)
    _expire(dsn, NAMESPACE, first.session_id)

    second_snapshot = ExtensionSnapshot(
        scope=_scope(ceiling),
        session_id=str(first.session_id),
        turn_id=str(derive_turn_id(first.session_id, 2)),
    )
    previous = stores.events.list_for_session(first.session_id)[-1]
    second = _accepted(
        second_snapshot,
        expected_revision=previous.sequence,
        sequence=previous.sequence + 1,
        key="second-bound-handoff",
    )
    stores.events.append_with_extension_snapshot(
        second, scope=second_snapshot.scope, snapshot=second_snapshot, task_ceiling=ceiling
    )
    assert _handoff(dsn, second).status is HandoffStatus.ACCEPTED

    recovered = recover_turn_extension(
        store=snapshots,
        events=stores.events.list_for_session(first.session_id),
        session_id=first.session_id,
        task_binding=ceiling.binding,
    )
    assert recovered is not None and recovered.snapshot == second_snapshot


def test_api_admits_second_message_after_rabbit_materializes_and_completes_first(
    dsn, tmp_path, monkeypatch
) -> None:
    service, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    snapshots = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshots.resolve_task_ceiling(session_id=str(session_id))
    admission = CloudExtensionTurnAdmission(
        PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE), snapshots, snapshots
    )
    request = {
        "kind": "message",
        "expected_revision": stores.sessions.get_session(session_id).current_sequence,
        "payload": {"content": "first admitted"},
    }
    first_response = submit_session_command(
        stores,
        str(session_id),
        request,
        idempotency_key="api-first-bound",
        extension_admission=admission,
        verified_host_grant=_verified_from_ceiling(ceiling),
    )
    assert first_response.status_code == 202
    first = stores.events.list_for_session(session_id)[-1]
    handed_off = _handoff(dsn, first)
    assert handed_off.status is HandoffStatus.ACCEPTED
    service.execute_claimed_session(handed_off.lease)

    current = stores.sessions.get_session(session_id)
    second_response = submit_session_command(
        stores,
        str(session_id),
        {
            "kind": "message",
            "expected_revision": current.current_sequence,
            "payload": {"content": "second admitted"},
        },
        idempotency_key="api-second-bound",
        extension_admission=admission,
        verified_host_grant=_verified_from_ceiling(ceiling),
    )
    assert second_response.status_code == 202


def test_api_refuses_distinct_canonical_and_legacy_materializations(
    dsn, tmp_path, monkeypatch
) -> None:
    _, stores, _, accepted, _, snapshots, ceiling = _bound_message(dsn, tmp_path, monkeypatch)
    events = stores.events.list_for_session(accepted.session_id)
    canonical = next(event for event in events if event.causation_id == accepted.event_id)
    legacy = canonical.model_copy(
        update={
            "event_id": uuid4(),
            "sequence": events[-1].sequence + 1,
            "causation_id": None,
            "idempotency_key": f"{accepted.idempotency_key}:message",
        }
    )
    stores.events.append(legacy)
    admission = CloudExtensionTurnAdmission(
        PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE), snapshots, snapshots
    )
    current_revision = stores.events.list_for_session(accepted.session_id)[-1].sequence
    response = submit_session_command(
        stores,
        str(accepted.session_id),
        {
            "kind": "message",
            "expected_revision": current_revision,
            "payload": {"content": "must not admit"},
        },
        idempotency_key="after-corrupt-history",
        extension_admission=admission,
        verified_host_grant=_verified_from_ceiling(ceiling),
    )
    assert response.status_code == 503
    assert response.body["status"] == "extension_admission_unavailable"


@pytest.mark.parametrize("corruption", ["missing", "causation"])
def test_bound_handoff_missing_or_tampered_correlation_fails_closed(
    dsn, tmp_path, monkeypatch, corruption
) -> None:
    service, stores, handed_off, accepted, _, snapshots, ceiling = _bound_message(
        dsn, tmp_path, monkeypatch
    )
    service.execute_claimed_session(handed_off.lease)
    input_id = _receipt(dsn, accepted)["input_event_id"]
    with psycopg.connect(dsn) as connection:
        if corruption == "missing":
            connection.execute(
                "UPDATE command_handoff_receipts SET input_event_id=NULL "
                "WHERE deployment_namespace=%s AND accepted_event_id=%s",
                (NAMESPACE, accepted.event_id),
            )
            connection.execute(
                "DELETE FROM task_event_index WHERE deployment_namespace=%s AND event_id=%s",
                (NAMESPACE, input_id),
            )
            connection.execute(
                "DELETE FROM session_events WHERE deployment_namespace=%s AND event_id=%s",
                (NAMESPACE, input_id),
            )
        else:
            connection.execute(
                "UPDATE session_events SET causation_id=%s WHERE deployment_namespace=%s "
                "AND event_id=%s",
                (uuid4(), NAMESPACE, input_id),
            )
    with pytest.raises(ValueError, match="missing canonical materialization"):
        recover_turn_extension(
            store=snapshots,
            events=stores.events.list_for_session(accepted.session_id),
            session_id=accepted.session_id,
            task_binding=ceiling.binding,
        )


@pytest.mark.parametrize("corruption", ["session", "fingerprint", "binding_deletion"])
def test_real_handoff_accepted_identity_tamper_fails_before_reads_or_attempt(
    dsn, tmp_path, monkeypatch, corruption
) -> None:
    _, stores, handed_off, accepted, _, snapshots, ceiling = _bound_message(
        dsn, tmp_path, monkeypatch
    )
    with psycopg.connect(dsn) as connection:
        if corruption == "session":
            connection.execute(
                "UPDATE session_events SET payload=jsonb_set(payload, '{session_id}', "
                "to_jsonb(%s::text)) WHERE deployment_namespace=%s AND event_id=%s",
                (str(uuid4()), NAMESPACE, accepted.event_id),
            )
        elif corruption == "fingerprint":
            connection.execute(
                "UPDATE session_events SET payload=jsonb_set(payload, '{payload,content}', "
                "to_jsonb(%s::text)) WHERE deployment_namespace=%s AND event_id=%s",
                ("tampered", NAMESPACE, accepted.event_id),
            )
        else:
            connection.execute(
                "UPDATE session_events SET payload=payload - 'extension_snapshot_digest' "
                "- 'extension_turn_id' WHERE deployment_namespace=%s AND event_id=%s",
                (NAMESPACE, accepted.event_id),
            )

    class CountingStore:
        ceiling_reads = 0
        snapshot_reads = 0
        existence_reads = 0

        def resolve_task_ceiling(self, *, session_id):
            self.ceiling_reads += 1
            return snapshots.resolve_task_ceiling(session_id=session_id)

        async def get(self, **kwargs):
            self.snapshot_reads += 1
            return await snapshots.get(**kwargs)

        async def exists(self, **kwargs):
            self.existence_reads += 1
            return await snapshots.exists(**kwargs)

    class NoAttemptWrite:
        def append(self, *_args, **_kwargs):
            raise AssertionError("attempt authority must not be persisted")

    extension_store = CountingStore()
    expected = (
        "missing its accepted command binding"
        if corruption == "binding_deletion"
        else "identity is not canonical|integrity check failed"
    )
    with pytest.raises(ValueError, match=expected):
        prepare_worker_context(
            store=None,
            task_binding_loader=lambda _: ceiling.binding,
            resolver=None,
            static_scope=None,
            scope_provider=None,
            recovery_service=cast(object, SimpleNamespace()),
            event_store=cast(object, SimpleNamespace()),
            recorder=cast(DurableHarnessEventRecorder, NoAttemptWrite()),
            claimed=cast(object, SimpleNamespace(lease=handed_off.lease)),
            events=stores.events.list_for_session(accepted.session_id),
            task=cast(RecoveredTask, SimpleNamespace()),
            active_capsule_id=None,
            as_of=datetime(2026, 9, 7, tzinfo=UTC),
            extension_store=cast(WorkerExtensionStore, extension_store),
        )
    expected_reads = (1, 0, 1) if corruption == "binding_deletion" else (0, 0, 0)
    assert (
        extension_store.ceiling_reads,
        extension_store.snapshot_reads,
        extension_store.existence_reads,
    ) == expected_reads


def test_bound_clarification_reuses_open_turn(dsn, tmp_path, monkeypatch) -> None:
    _, stores, session_id = _awaiting(dsn, tmp_path, monkeypatch)
    original = _message(dsn, session_id)
    lease = _handoff(dsn, original).lease
    _refresh(dsn, session_id)
    _start(dsn, original, lease)
    clarification_id = str(uuid4())
    requested = _event(
        dsn,
        session_id,
        EventType.CLARIFICATION_REQUESTED,
        {"clarification_id": clarification_id},
    )
    _commit(dsn, requested, lease)
    _expire(dsn, NAMESPACE, session_id)
    turn_id = current_turn(stores.events.list_for_session(session_id)).turn_id

    snapshots = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshots.resolve_task_ceiling(session_id=str(session_id))
    snapshot = ExtensionSnapshot(scope=_scope(ceiling), session_id=str(session_id), turn_id=turn_id)
    previous = stores.events.list_for_session(session_id)[-1]
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=previous.sequence,
        idempotency_key="bound-clarification",
        payload={"content": "answer", "clarification_id": clarification_id},
    )
    accepted = SessionEvent.create(
        session_id=session_id,
        sequence=previous.sequence + 1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(
            extension_snapshot_digest=snapshot.digest, extension_turn_id=turn_id
        ),
        idempotency_key=command.idempotency_key,
    )
    stores.events.append_with_extension_snapshot(
        accepted, scope=snapshot.scope, snapshot=snapshot, task_ceiling=ceiling
    )
    assert _handoff(dsn, accepted).status is HandoffStatus.ACCEPTED
    events = stores.events.list_for_session(session_id)
    response = next(event for event in events if event.causation_id == accepted.event_id)
    assert response.event_type is EventType.CLARIFICATION_RESPONDED
    assert "turn_id" not in response.payload and current_turn(events).turn_id == turn_id
    assert (
        recover_turn_extension(
            store=snapshots, events=events, session_id=session_id, task_binding=ceiling.binding
        ).snapshot
        == snapshot
    )
