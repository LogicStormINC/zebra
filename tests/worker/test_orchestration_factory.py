"""Native published Registry identities, real Task binding and fail-closed dispatch."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_definitions import AgentDefinition, AgentRelease
from agent_core.domain.bundle_definition import BundleDefinitionSnapshot
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_core.ports.worker_budget import ModelRequestBudget, WorkerBudgetBinding
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_orchestration.application.orchestration_port import OrchestrationToolError
from agent_orchestration.domain.orchestration import (
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
)
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.leases import acquire_lease_in_transaction
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.work_unit import postgres_work_unit
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
from zebra_agent_worker.orchestration_composition import PostgresOrchestrationFactory
from zebra_agent_worker.task_recovery import recover_task
from zebra_agent_worker.worker_budget import TaskBudgetGate

from tests.agent_core.test_bundle_definition import assembly_payload, bundle_version
from tests.agent_storage.test_command_wakeup import _binding


class TrustedFixtureGateway(OpenAICompatibleModelGateway):
    """Known wire alphabet fixture counter, never the external default provider."""

    def __init__(self):
        super().__init__(
            provider_name="fixture",
            base_url="https://fixture.invalid",
            api_key="fixture",
            model_name="fixture",
            client=httpx.Client(transport=httpx.MockTransport(self._no_send)),
        )
        self.model_request_budget = self._counter

    @staticmethod
    def _no_send(request):
        raise AssertionError("factory checks do not send a model request")

    @staticmethod
    def _counter(body):
        output_cap = json.loads(body)["max_tokens"]
        return ModelRequestBudget(
            body, sha256(body).hexdigest(), len(body), output_cap, "fixture-byte-upper/1"
        )


def _publish(factory, name, **version_changes):
    assembly = assembly_payload()
    assembly["bundle"]["manifest"]["scope"]["namespace_id"] = factory.namespace
    assembly["bundle"]["bundle_digest"] = json_digest(assembly["bundle"]["manifest"])
    version = bundle_version(
        namespace_id=factory.namespace,
        runtime_assembly=RuntimeAssembly.model_validate(assembly),
        **version_changes,
    )
    definition = AgentDefinition(
        definition_id=version.definition_id,
        authority_issuer=version.authority_issuer,
        namespace_id=version.namespace_id,
        name=name,
        created_at=datetime.now(UTC),
    )
    registry = factory.roles.registry
    registry.save_definition(definition)
    registry.save_version(version)
    release = AgentRelease.from_version(
        version,
        release_id=uuid4(),
        environment=version.runtime_assembly.bundle.manifest.scope.environment,
        actor_ref="trusted-fixture-publisher",
        effective_at=datetime.now(UTC),
    )
    registry.append_release(release)
    return BundleDefinitionSnapshot.from_release(
        release=release,
        version=version,
        resolved_at=datetime.now(UTC),
    )


@pytest.fixture
def native(request):
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("requires the explicitly owned PostgreSQL DSN")
    apply_postgres_migrations(dsn)
    ns = "factory-" + uuid4().hex
    bootstrap_control_plane_epoch(dsn, deployment_namespace=ns)
    factory = PostgresOrchestrationFactory(dsn, ns)
    options = dict(getattr(request, "param", {}))
    legacy_binding = options.pop("legacy_binding", False)
    snapshot = _publish(factory, "system/orchestrator", **options)
    role = _publish(factory, "system/researcher")
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Native orchestrator",
            user_input="Analyze",
            workspace_root=Path("/tmp/factory"),
            definition_snapshot=snapshot,
        )
    )
    parent = _binding(str(boot.session.session_id))
    caps = frozenset({"agent.execute", "orchestration.plan.propose", "orchestration.task.request"})
    parent = parent.model_copy(
        update={
            "effective_capabilities": caps,
            "agent_capability_ceiling": parent.agent_capability_ceiling.model_copy(
                update={
                    "definition_snapshot_digest": snapshot.definition_digest
                    if legacy_binding
                    else snapshot.snapshot_digest,
                    "capabilities": caps,
                }
            ),
            "host_capability": parent.host_capability.model_copy(
                update={
                    "capabilities": caps,
                    "grant_expires_at": parent.host_capability.host_context.expires_at,
                }
            ),
        }
    )
    workspace = rebuild_workspace(list(boot.events))
    proof = BoundHostExecutionAuthorityResolver(parent).resolve_for_attempt(
        ExecutionAuthorityResolutionRequest(
            session_id=boot.session.session_id,
            attempt_number=1,
            scope=OpaqueAuthorityScope(
                authority_issuer=parent.host_capability.authority_issuer,
                namespace_id=parent.host_capability.namespace_id,
            ),
            validated_at=datetime.now(UTC),
        )
    )
    authority_event = SessionEvent.create(
        session_id=boot.session.session_id,
        sequence=len(boot.events),
        event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
        actor=EventActor.SYSTEM,
        payload=proof.model_dump(mode="json"),
    )
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=ns).admit(
        TaskAdmissionRequest(
            events=(*boot.events, authority_event),
            session=boot.session,
            workspace=workspace,
            binding=parent,
        )
    )
    with factory.database.connect() as c:
        lease = acquire_lease_in_transaction(
            c,
            ns,
            boot.session.session_id,
            owner_instance_id="factory-worker",
            ttl=timedelta(seconds=120),
        )
    budget = WorkerBudgetBinding(
        parent.task_id, boot.session.session_id, parent.binding_digest, lease.fence, 1, 100, 60, 20
    )
    gate = TaskBudgetGate(factory.budgets, budget)
    gate.start()
    gateway = TrustedFixtureGateway()
    gate.attach_model(gateway)
    task = recover_task(
        list(boot.events), workspace=workspace, fallback_title="Native", attachment_reader=None
    )
    return factory, task, parent, gateway, lease.fence, role, authority_event


def _runtime(native, **changes):
    factory, task, parent, model, fence, _, _ = native
    return factory(
        **{
            "task": task,
            "binding": parent,
            "fence": fence,
            "model_gateway": model,
            "attempt_number": 1,
            **changes,
        }
    )


def _proposal():
    return OrchestrationPlanProposal(
        objective="Inspect",
        synthesis_instruction="Summarize",
        max_parallelism=1,
        nodes=(
            OrchestrationNodeProposal(
                node_key="inspect",
                objective="Read",
                preferred_agent_role="researcher",
                required_capabilities=frozenset({"agent.execute"}),
                max_model_tokens=10,
                max_model_calls=1,
                max_tool_calls=1,
                max_runtime_seconds=5,
            ),
        ),
    )


def test_published_parent_native_binding_and_real_child_snapshot(native):
    factory, task, parent, _, _, role, _ = native
    runtime = _runtime(native)
    receipt = runtime.propose_plan(_proposal())
    snapshot = factory.store.get_snapshot(receipt.run_ref)
    assert snapshot is not None
    assert factory.store.read_run_status(receipt.run_ref) == "running"
    with runtime._authorized("request") as authority:
        prepared = factory._builder(task, task.definition_snapshot)(
            authority, parent, snapshot, snapshot.nodes[0].proposal
        )
        prepared.validate(authority, parent, snapshot, snapshot.nodes[0].proposal)
    payload = prepared.admission.events[2].payload["definition_snapshot"]
    assert payload["definition_id"] == str(role.definition_id)
    assert payload["bound_version"][
        "runtime_assembly"
    ] == role.bound_version.runtime_assembly.model_dump(mode="json")
    assert (
        prepared.admission.binding.agent_capability_ceiling.definition_snapshot_digest
        == payload["snapshot_digest"]
    )
    # Parent counter does not prove this independently selected child's transport.
    with pytest.raises(OrchestrationToolError, match="executor budget guard"):
        runtime.request_task(run_ref=receipt.run_ref, node_key="inspect")


def test_missing_counter_and_wrong_fence_are_refused(native):
    runtime = _runtime(native, model_gateway=object())
    with pytest.raises(OrchestrationToolError, match="trusted cumulative"):
        runtime.propose_plan(_proposal())
    fence = native[4].model_copy(update={"fencing_token": native[4].fencing_token + 1})
    with pytest.raises(OrchestrationToolError, match="trusted cumulative"):
        _runtime(native, fence=fence).propose_plan(_proposal())


def test_non_orchestrator_and_profile_spoof_do_not_get_runtime(native):
    ordinary = replace(native[1], definition_snapshot=native[5])
    assert _runtime(native, task=ordinary) is None
    assert _runtime(native, task=replace(ordinary, definition_snapshot=None)) is None


def test_registry_ambiguity_and_latest_native_denial_fail_closed(native):
    factory, _, _, _, _, _, prior = native
    _publish(factory, "system/researcher")
    with pytest.raises(OrchestrationToolError, match="ambiguous"):
        _runtime(native).propose_plan(_proposal())
    denied = dict(prior.payload)
    denied["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    denied["issued_at"] = datetime.now(UTC) - timedelta(seconds=20)
    denied.pop("snapshot_digest")
    from agent_core.domain.execution_authority import ExecutionAuthoritySnapshot

    denied = ExecutionAuthoritySnapshot.model_validate(denied).model_dump(mode="json")
    PostgresEventStore(factory.database._dsn, deployment_namespace=factory.namespace).append(
        SessionEvent.create(
            session_id=prior.session_id,
            sequence=prior.sequence + 1,
            event_type=prior.event_type,
            actor=prior.actor,
            payload=denied,
        )
    )
    with pytest.raises(OrchestrationToolError, match="durable execution authority"):
        _runtime(native).propose_plan(_proposal())


def test_unpublished_or_missing_registry_snapshot_cannot_authorize(native):
    factory, task, _, _, _, _, _ = native
    with postgres_work_unit(factory.database), factory.database.connect() as c:
        c.execute(
            "UPDATE agent_release_records SET status='revoked',reason_class='fixture' "
            "WHERE authority_issuer=%s AND namespace_id=%s AND definition_id=%s",
            task.definition_snapshot.scope.scope_key,
        )
    with pytest.raises(OrchestrationToolError, match="published|revoked"):
        _runtime(native)


def test_shared_child_counter_resolver_real_admission_and_terminal_settlement(native, monkeypatch):
    from agent_core.domain.task_bindings import TaskBindingSnapshot
    from agent_orchestration.application.orchestration_admission import original_key

    factory, _, parent, _, _, role, _ = native
    monkeypatch.setenv(role.bound_version.runtime_assembly.provider_profile.api_key_env, "fixture")
    inspected = []

    def counters(model, assembly):
        # One server-side resolver must inspect the ACTUAL frozen child provider/model.
        if (
            assembly is None
            or model._assembly != assembly
            or assembly.provider_profile.base_url != "https://models.example/v1"
            or model._model_name != assembly.bundle.manifest.domains.model.parameters.model
        ):
            return None
        inspected.append(assembly.assembly_digest)
        return TrustedFixtureGateway._counter

    factory.model_request_budget_factory = counters
    runtime = _runtime(native)
    receipt = runtime.propose_plan(_proposal())
    child = runtime.request_task(run_ref=receipt.run_ref, node_key="inspect")
    assert inspected == [role.bound_version.runtime_assembly.assembly_digest] * 3
    snapshot = factory.store.get_snapshot(receipt.run_ref)
    key = original_key(factory.namespace, snapshot, "inspect")
    # Without an ordinary child's durable usage, the full original stays reserved.
    assert factory.settle_original(key, parent.task_id) is False
    with factory.database.connect() as c:
        durable = c.execute(
            "SELECT snapshot_json FROM task_binding_snapshots "
            "WHERE deployment_namespace=%s AND task_id=%s "
            "ORDER BY binding_revision DESC LIMIT 1",
            (factory.namespace, child.child_task_id),
        ).fetchone()
    child_binding = TaskBindingSnapshot.model_validate(durable["snapshot_json"])
    assert isinstance(child_binding, TaskBindingSnapshot)
    with factory.database.connect() as c:
        child_row = c.execute(
            "SELECT active_segment_id FROM agent_tasks "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (factory.namespace, child.child_task_id),
        ).fetchone()
        lease = acquire_lease_in_transaction(
            c,
            factory.namespace,
            child_row["active_segment_id"],
            owner_instance_id="real-child-worker",
            ttl=timedelta(seconds=30),
        )
    guarded = WorkerBudgetBinding(
        child.child_task_id,
        child_row["active_segment_id"],
        child_binding.binding_digest,
        lease.fence,
        1,
        10,
        5,
        1,
    )
    factory.budgets.start(guarded)
    body = b'{"max_tokens":1}'
    reservation = factory.budgets.reserve_model(
        guarded,
        ModelRequestBudget(body, sha256(body).hexdigest(), 2, 1, "fixture-known-vocabulary/1"),
    )
    factory.budgets.settle_model(
        guarded,
        reservation,
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "trusted-child-provider-receipt",
    )
    events = PostgresEventStore(factory.database._dsn, deployment_namespace=factory.namespace)
    current = events.read_since(guarded.session_id, -1)
    events.append(
        SessionEvent.create(
            session_id=guarded.session_id,
            sequence=current[-1].sequence + 1,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "fixture completed"},
        )
    )
    # Native projection is independently updated by the ordinary execution path.
    with factory.database.connect() as c:
        c.execute(
            "UPDATE session_projections SET status='completed' "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (factory.namespace, guarded.session_id),
        )
    assert factory.settle_original(key, parent.task_id) is True
    assert factory.settle_original(key, parent.task_id) is True


def test_prepared_child_rechecks_publication_without_poisoning_later_calls(native):
    factory, task, parent, _, _, role, _ = native
    runtime = _runtime(native)
    receipt = runtime.propose_plan(_proposal())
    snapshot = factory.store.get_snapshot(receipt.run_ref)
    node = snapshot.nodes[0].proposal
    with runtime._authorized("request") as authority:
        prepared = factory._builder(task, task.definition_snapshot)(
            authority, parent, snapshot, node
        )
    with factory.database.connect() as c:
        c.execute(
            "UPDATE agent_release_records SET status='revoked',reason_class='fixture' "
            "WHERE authority_issuer=%s AND namespace_id=%s AND definition_id=%s",
            role.scope.scope_key,
        )
    with pytest.raises(OrchestrationToolError, match="published|revoked"):
        prepared.validate(authority, parent, snapshot, node)
    _publish(factory, "system/researcher")
    assert runtime.propose_plan(_proposal()).run_ref != receipt.run_ref


def test_parent_release_upgrade_preserves_frozen_run_and_explicit_revoke_denies(native):
    from agent_core.domain.bundle_definition import BundleDefinitionVersion

    factory, task, parent, _, _, _, _ = native
    original = task.definition_snapshot
    runtime = _runtime(native)
    receipt = runtime.propose_plan(_proposal())
    version = BundleDefinitionVersion.model_validate(
        {
            **original.bound_version.model_dump(),
            "version_id": uuid4(),
            "version": 2,
            "definition_digest": None,
        }
    )
    factory.roles.registry.save_version(version)
    release = AgentRelease.from_version(
        version,
        release_id=uuid4(),
        environment=version.runtime_assembly.bundle.manifest.scope.environment,
        actor_ref="trusted-upgrade",
        effective_at=datetime.now(UTC),
    )
    factory.roles.registry.append_release(release)
    # A restarted Worker and existing run still use the ORIGINAL embedded assembly.
    recovered = _runtime(native)
    assert recovered is not None
    assert (
        factory.store.get_snapshot(receipt.run_ref).parent_binding_digest == parent.binding_digest
    )
    with recovered._authorized("request") as authority:
        assert authority.parent_binding_digest == parent.binding_digest
    assert recovered.propose_plan(_proposal()).run_ref != receipt.run_ref
    with factory.database.connect() as c:
        c.execute(
            "UPDATE agent_release_records SET status='revoked',reason_class='fixture' "
            "WHERE authority_issuer=%s AND namespace_id=%s AND definition_id=%s "
            "AND release_id=%s",
            (*original.scope.scope_key, original.release_id),
        )
    with pytest.raises(OrchestrationToolError, match="revoked"):
        _runtime(native)


@pytest.mark.parametrize("native", [{"legacy_binding": True}], indirect=True)
def test_public_legacy_bundle_binding_and_new_child_binding_are_both_exact(native):
    factory, task, parent, _, _, _, _ = native
    assert (
        parent.agent_capability_ceiling.definition_snapshot_digest
        == task.definition_snapshot.definition_digest
    )
    runtime = _runtime(native)
    receipt = runtime.propose_plan(_proposal())
    snapshot = factory.store.get_snapshot(receipt.run_ref)
    with runtime._authorized("request") as authority:
        child = factory._builder(task, task.definition_snapshot)(
            authority, parent, snapshot, snapshot.nodes[0].proposal
        )
    assert (
        child.admission.binding.agent_capability_ceiling.definition_snapshot_digest
        != parent.agent_capability_ceiling.definition_snapshot_digest
    )
    assert (
        child.admission.binding.agent_capability_ceiling.definition_snapshot_digest
        == child.admission.events[2].payload["definition_snapshot"]["snapshot_digest"]
    )
    wrong = parent.model_copy(
        update={
            "agent_capability_ceiling": parent.agent_capability_ceiling.model_copy(
                update={"definition_snapshot_digest": "f" * 64},
            )
        }
    )
    with pytest.raises(OrchestrationToolError, match="real Task Definition snapshot"):
        _runtime(native, binding=wrong)
