"""Live control and publication races on an owned native PostgreSQL."""
# ruff: noqa: F811

import sys
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus

from tests.agent_core.test_native_script_binding import assembly_and_config, binding
from tests.worker.test_native_script_worker import (  # noqa: F401
    native_parts,
    owned_dsn,
    provider,
    script_dsn,
    setup,
    worker,
)


@pytest.mark.skipif(sys.platform != "darwin", reason="actual native Seatbelt live control")
@pytest.mark.parametrize("control", ["host", "lease", "stop"])
def test_live_script_control_has_no_late_receipt(script_dsn, tmp_path, monkeypatch, control):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from uuid import UUID

    from agent_core.application.native_script import NativeScriptUnavailable
    from agent_core.domain.leases import LeaseLostError
    from agent_runtime import OsSandboxRuntime
    from agent_storage.postgres.direct_control import PostgresDirectControl
    from zebra_agent_worker.execution_events import ExecutionInterrupted

    source = (
        "def execute(arguments):\n    import time\n    time.sleep(5)\n    return {'value':'late'}\n"
    )
    configured, stores, claims, bound, host, record, _ = setup(
        script_dsn, tmp_path, tool_source=source
    )
    tools, recorder, lease = native_parts(configured, stores, claims, bound, tmp_path)
    entered = Event()
    execute = OsSandboxRuntime.execute

    def observed(self, request):
        entered.set()
        return execute(self, request)

    monkeypatch.setattr(OsSandboxRuntime, "execute", observed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            tools.service.invoke, binding("tool", source), {"query": "x"}, logical_id="live"
        )
        assert entered.wait(5)
        sleep(0.1)
        start = monotonic()
        if control == "host":
            host.upsert_registry(replace(record, active=False))
            expected = NativeScriptUnavailable
        elif control == "lease":
            stores.leases.release(lease.session_id, fence=lease.fence)
            stores.leases.acquire(
                lease.session_id, owner_instance_id="takeover", ttl=timedelta(seconds=60)
            )
            expected = LeaseLostError
        else:
            PostgresDirectControl(
                script_dsn, deployment_namespace=stores.deployment_namespace
            ).cancel(
                UUID(bound.task_id),
                scope=OpaqueAuthorityScope(
                    authority_issuer=bound.host_capability.authority_issuer,
                    namespace_id=bound.host_capability.namespace_id,
                ),
                host_context=bound.host_capability.host_context,
                workspace_ref=bound.host_capability.host_context.workspace_ref,
            )
            # Cancel revokes the lease as well as the session. Either current
            # check may observe that transaction first; both must stop output.
            expected = (ExecutionInterrupted, LeaseLostError)
        with pytest.raises(expected):
            future.result(timeout=3)
        assert monotonic() - start < 2
    events = stores.events.list_for_session(lease.session_id)
    assert [
        e.payload["phase"] for e in events if e.event_type is EventType.NATIVE_SCRIPT_INVOCATION
    ] == ["started"]
    if control == "stop":
        assert stores.sessions.get_session(lease.session_id).status is SessionStatus.CANCELLED
    if control == "lease":
        from agent_core.domain.events import EventActor

        with pytest.raises(LeaseLostError):
            recorder.append(
                EventType.NATIVE_SCRIPT_INVOCATION,
                EventActor.HARNESS,
                next(
                    e.payload for e in events if e.event_type is EventType.NATIVE_SCRIPT_INVOCATION
                ),
            )


@pytest.mark.skipif(
    sys.platform != "darwin", reason="actual native Seatbelt final publication gate"
)
def test_host_revocation_after_verifier_prevents_answer_commit(script_dsn, tmp_path, monkeypatch):
    from agent_core.application.native_script import NativeScriptInvocationService

    configured, stores, claims, bound, host, record, _ = setup(script_dsn, tmp_path)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "test-only")
    invoke = NativeScriptInvocationService.invoke

    def revoke(self, item, arguments, *, logical_id):
        result = invoke(self, item, arguments, logical_id=logical_id)
        if item.manifest.kind == "verifier":
            host.upsert_registry(replace(record, active=False))
        return result

    monkeypatch.setattr(NativeScriptInvocationService, "invoke", revoke)
    with provider([]) as client:
        result = worker(configured, stores, claims, bound, client, tmp_path).execute_session(
            __import__("uuid").UUID(bound.task_id), worker_id="final-race"
        )
    assert result.session.status is SessionStatus.FAILED
    assert not any(
        e.event_type is EventType.ANSWER_COMMITTED
        for e in stores.events.list_for_session(result.session.session_id)
    )


def test_host_disable_serializes_with_actual_leased_receipt_append(script_dsn, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from agent_core.application.native_script import NativeScriptUnavailable
    from agent_core.domain.events import EventActor
    from agent_storage.postgres.native_script_authority import NativeScriptAuthority

    configured, stores, claims, bound, host, record, _ = setup(script_dsn, tmp_path)
    tools, recorder, lease = native_parts(configured, stores, claims, bound, tmp_path)
    authority = NativeScriptAuthority(stores.events, bound)
    locked, release = Event(), Event()

    def append():
        def mutation():
            locked.set()
            assert release.wait(2)
            from agent_core.domain.native_script_receipt import NativeScriptEvent

            payload = NativeScriptEvent(
                schema_version="cloud-agent.native-script-event/1",
                invocation_id=str(uuid4()),
                task_id=bound.task_id,
                snapshot_digest="sha256:" + "a" * 64,
                binding_digest="sha256:" + "b" * 64,
                input_digest="sha256:" + "c" * 64,
                owner_fence=tools.service.owner_fence,
                execution_attempt=1,
                phase="started",
            )
            return recorder.append(
                EventType.NATIVE_SCRIPT_INVOCATION,
                EventActor.HARNESS,
                payload.model_dump(mode="json"),
            )

        return authority.checked(mutation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(append)
        assert locked.wait(2)
        disabling = pool.submit(host.upsert_registry, replace(record, active=False))
        from time import sleep

        sleep(0.1)
        assert not disabling.done()
        release.set()
        assert writing.result(timeout=3).event_type is EventType.NATIVE_SCRIPT_INVOCATION
        assert not disabling.result(timeout=3).active
    with pytest.raises(NativeScriptUnavailable):
        authority.checked(lambda: pytest.fail("revoked transaction executed"))


def test_script_materialization_and_publication_need_separate_exact_grant(script_dsn, tmp_path):
    from agent_core.application.agent_definitions import (
        AgentDefinitionDraftService,
        PublisherGrantCeiling,
        PublisherGrantError,
        StaticPublisherGrantResolver,
    )
    from agent_core.application.agent_publication import (
        AgentDefinitionPublicationService,
        PublicationGateEvidence,
    )
    from agent_core.domain.identifiers import AgentDefinitionId, AgentDefinitionVersionId
    from agent_storage.postgres.agent_registry import PostgresAgentRegistry

    from tests.agent_core.test_bundle_definition import NOW, REFERENCES

    assembly, _, _ = assembly_and_config(tmp_path)
    scope = assembly.bundle.manifest.scope
    base_ref = "runtime-bundle/" + assembly.bundle.bundle_digest.removeprefix("sha256:") + "@1"
    references = frozenset([*REFERENCES.values(), base_ref])

    def grants(refs):
        return StaticPublisherGrantResolver(
            {
                "publisher@" + scope.namespace_id: PublisherGrantCeiling(
                    scope.authority_issuer, scope.namespace_id, refs
                )
            }
        )

    registry = PostgresAgentRegistry(script_dsn, deployment_namespace="native-script-publisher")
    service = AgentDefinitionDraftService(registry, grants(references))
    definition_id = AgentDefinitionId(uuid4())
    service.create_draft(
        definition_id=definition_id,
        namespace_id=scope.namespace_id,
        actor_ref="publisher",
        name="native-script",
        description="test",
        skill_snapshot_digest="a" * 64,
        updated_at=NOW,
        **REFERENCES,
    )
    service.validate_draft(
        definition_id=definition_id,
        namespace_id=scope.namespace_id,
        actor_ref="publisher",
        evaluated_at=NOW,
    )
    args = dict(
        definition_id=definition_id,
        namespace_id=scope.namespace_id,
        actor_ref="publisher",
        version_id=AgentDefinitionVersionId(uuid4()),
        version=1,
        created_at=NOW,
        runtime_assembly=assembly,
    )
    with pytest.raises(PublisherGrantError, match="script Bundle"):
        service.materialize_version(**args)
    approved = grants(references | {assembly.required_reference})
    materialized = AgentDefinitionDraftService(registry, approved).materialize_version(**args)
    assert materialized.schema_version == "agent-definition/3"
    gate = PublicationGateEvidence(
        materialized.version_id, materialized.definition_digest, True, "policy/1"
    )
    publish = dict(
        version_id=materialized.version_id,
        environment=scope.environment,
        actor_ref="publisher",
        gate=gate,
        effective_at=NOW,
    )
    with pytest.raises(ValueError, match="script Bundle"):
        AgentDefinitionPublicationService(registry, grants(references)).publish(
            materialized.scope, **publish
        )
    release = AgentDefinitionPublicationService(registry, approved).publish(
        materialized.scope, **publish
    )
    from agent_core.domain.bundle_definition import parse_definition_snapshot, snapshot_from_release

    snapshot = snapshot_from_release(release=release, version=materialized, resolved_at=NOW)
    assert parse_definition_snapshot(snapshot).bound_version == materialized


@pytest.mark.skipif(sys.platform != "darwin", reason="actual native Seatbelt terminal replay")
def test_current_postgres_host_revocation_also_refuses_completed_replay(script_dsn, tmp_path):
    from agent_core.application.native_script import NativeScriptUnavailable

    configured, stores, claims, bound, host, record, _ = setup(script_dsn, tmp_path)
    tools, _, lease = native_parts(configured, stores, claims, bound, tmp_path)
    first = tools.service.invoke(binding(), {"query": "x"}, logical_id="terminal")
    assert first.output_json
    host.upsert_registry(replace(record, active=False))
    with pytest.raises(NativeScriptUnavailable, match="HOST_AUTHORITY"):
        tools.service.invoke(binding(), {"query": "x"}, logical_id="terminal")
    assert (
        sum(
            e.event_type is EventType.NATIVE_SCRIPT_INVOCATION
            for e in stores.events.list_for_session(lease.session_id)
        )
        == 2
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="actual Worker uncertain commit boundary")
def test_worker_does_not_finalize_an_uncertain_script_receipt(script_dsn, tmp_path, monkeypatch):
    from agent_core.application.native_script import NativeScriptReceiptUncertain
    from agent_storage.postgres.native_script_authority import PostgresScriptJournal

    configured, stores, claims, bound, _, _, _ = setup(script_dsn, tmp_path)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "test-only")
    append = PostgresScriptJournal.append

    def uncertain(self, event):
        append(self, event)
        if event.phase == "completed":
            raise NativeScriptReceiptUncertain("owned lost ACK after real commit")

    monkeypatch.setattr(PostgresScriptJournal, "append", uncertain)
    with provider([]) as client, pytest.raises(NativeScriptReceiptUncertain):
        worker(configured, stores, claims, bound, client, tmp_path).execute_session(
            __import__("uuid").UUID(bound.task_id), worker_id="uncertain-worker"
        )
    events = stores.events.list_for_session(__import__("uuid").UUID(bound.task_id))
    assert not any(
        e.event_type
        in {EventType.ANSWER_COMMITTED, EventType.SESSION_COMPLETED, EventType.SESSION_FAILED}
        for e in events
    )
    assert [
        e.payload["phase"] for e in events if e.event_type is EventType.NATIVE_SCRIPT_INVOCATION
    ] == ["started", "completed"]


@pytest.mark.skipif(sys.platform != "darwin", reason="actual final answer transaction failure")
@pytest.mark.parametrize("unknown", ["rollback", "committed-ack-lost"])
def test_final_answer_transaction_uncertainty_never_uses_recorder_cache(
    script_dsn,
    tmp_path,
    monkeypatch,
    unknown,
):
    from uuid import UUID

    import psycopg
    from agent_core.application.native_script import NativeScriptReceiptUncertain
    from agent_storage.postgres.native_script_authority import NativeScriptAuthority

    configured, stores, claims, bound, _, _, _ = setup(script_dsn, tmp_path)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "test-only")
    checked = NativeScriptAuthority.checked

    def fault(self, action):
        changed = False

        def wrapped():
            nonlocal changed
            with self._database.connect() as connection:
                before = connection.execute(
                    "SELECT count(*) AS count FROM session_events "
                    "WHERE event_type='answer_committed'"
                ).fetchone()["count"]
            result = action()
            with self._database.connect() as connection:
                after = connection.execute(
                    "SELECT count(*) AS count FROM session_events "
                    "WHERE event_type='answer_committed'"
                ).fetchone()["count"]
            changed = after > before
            if changed and unknown == "rollback":
                raise psycopg.OperationalError("owned failure before real transaction exit")
            return result

        result = checked(self, wrapped)
        if changed and unknown == "committed-ack-lost":
            raise psycopg.OperationalError("owned lost ACK after real commit")
        return result

    monkeypatch.setattr(NativeScriptAuthority, "checked", fault)
    with provider([]) as client, pytest.raises(NativeScriptReceiptUncertain):
        worker(configured, stores, claims, bound, client, tmp_path).execute_session(
            UUID(bound.task_id), worker_id="uncertain-answer"
        )
    events = stores.events.list_for_session(UUID(bound.task_id))
    assert sum(e.event_type is EventType.ANSWER_COMMITTED for e in events) == (
        unknown == "committed-ack-lost"
    )
    assert not any(
        e.event_type in {EventType.SESSION_COMPLETED, EventType.SESSION_FAILED} for e in events
    )
