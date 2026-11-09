"""One assertion-only check; run in pinned105 Worker with overlay_imports.

No real model, network, database, allocator or production mutations. SQL seams
use strict recording doubles; actual PostgreSQL concurrency remains a separate gate.
"""

import overlay_imports as overlay_imports

# isort: split

import os
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import UUID as UUID
from uuid import uuid4 as uuid4

from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
    host_context_digest,
)
from agent_core.domain.workspace_control import (
    WorkspaceInstance,
    WorkspaceSource,
)
from agent_storage.postgres import erp_workspace_policy as policy
from agent_storage.postgres import projections
from zebra_agent_worker import cloud_memory_recovery, execution, execution_recovery
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.command_rejections import command_rejected

NOW = datetime.now(UTC)
SID = SessionId(uuid4())
WID = uuid4()
THREAD = str(uuid4())
REF = "erp-u-" + "a" * 40
LOCATOR = f"erpnext://private-workspace/v1/{THREAD}/{REF}"
CAPS = capability_set(["agent.execute", "evidence.read"])
CONTEXT = HostContextEnvelope(
    grant_id="qa",
    host_app_id="erpnext",
    namespace_id="erpnext",
    workspace_ref=REF,
    resource_refs=(
        HostResourceRef(type="thread", id=THREAD),
        HostResourceRef(type="principal", id="qa-user"),
    ),
    scopes=("agent.run",),
    limits=HostTechnicalLimits(max_runtime_seconds=10, max_model_tokens=10, max_artifact_bytes=10),
    origin="https://erpnext.zebra.local",
    policy_version="v1",
    expires_at=NOW + timedelta(minutes=5),
)
HOST = HostCapabilitySnapshot(
    host_app_id="erpnext",
    authority_issuer="https://erpnext.zebra.local",
    namespace_id="erpnext",
    grant_digest=host_context_digest(CONTEXT),
    host_context=CONTEXT,
    connector_id="erp",
    connector_profile_revision=1,
    connector_profile_digest="c" * 64,
    manifest_digest="d" * 64,
    capabilities=CAPS,
    resource_binding_digest="e" * 64,
    bound_at=NOW,
)
BINDING = TaskBindingSnapshot(
    task_id=str(SID),
    agent_capability_ceiling=AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="b" * 64,
        capability_profile_ref="profile/default@1",
        capabilities=CAPS,
        resolved_at=NOW,
    ),
    host_capability=HOST,
    zebra_policy_digest="f" * 64,
    effective_capabilities=CAPS,
    binding_revision=1,
    bound_at=NOW,
)
INSTANCE = WorkspaceInstance(
    workspace_id=WID,
    deployment_namespace="erpnext",
    source=WorkspaceSource(kind="host_reference", locator=LOCATOR),
    state="pending",
    owner_session_id=SID,
    quota_bytes=100,
)


def refuses(fn, code):
    try:
        fn()
    except policy.ERPWorkspacePolicyRefusal as error:
        assert error.code == code, error.code
        assert not isinstance(error, execution.WorkerExecutionError)
    else:
        raise AssertionError("Execution was not refused: " + code)


with patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "disabled"}):
    assert not policy.containment_enabled("erpnext")
    assert policy.eligible_execution_sql("trench") == ""
with patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}):
    assert policy.eligible_execution_sql("erpnext") == " AND FALSE "
    for namespace in ("trench", None):
        try:
            policy.containment_enabled(namespace)
        except ValueError:
            pass
        else:
            raise AssertionError("Cross-deployment configuration accepted")

assert policy.is_private_generation(BINDING, INSTANCE, task_id=str(SID))
for locator in (
    "/var/lib/zebra/erpnext-workspaces",
    LOCATOR + "/",
    LOCATOR + "?x=1",
    LOCATOR.replace("erpnext://", "erpnext:/"),
    LOCATOR.replace(THREAD, str(uuid4())),
    LOCATOR.replace(REF, "erp-u-" + "A" * 40),
    LOCATOR.replace("v1/", "v1/../v1/"),
):
    instance = INSTANCE.model_copy(
        update={"source": INSTANCE.source.model_copy(update={"locator": locator})}
    )
    assert not policy.is_private_generation(BINDING, instance, task_id=str(SID)), locator
for changed in (
    {"authority_issuer": "https://other.example"},
    {"host_app_id": "trench"},
    {"namespace_id": "other"},
    {"grant_digest": "0" * 64},
):
    assert not policy.is_private_generation(
        BINDING.model_copy(update={"host_capability": HOST.model_copy(update=changed)}),
        INSTANCE,
        task_id=str(SID),
    )
for resources in (
    (HostResourceRef(type="principal", id="user"),),
    CONTEXT.resource_refs + (HostResourceRef(type="thread", id=str(uuid4())),),
    CONTEXT.resource_refs + (HostResourceRef(type="principal", id="other"),),
):
    context = CONTEXT.model_copy(update={"resource_refs": resources})
    host = HOST.model_copy(
        update={"host_context": context, "grant_digest": host_context_digest(context)}
    )
    assert not policy.is_private_generation(
        BINDING.model_copy(update={"host_capability": host}), INSTANCE, task_id=str(SID)
    )


class Row:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value

    def fetchall(self):
        return []


class Database:
    deployment_namespace = "erpnext"

    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def connect_task_io(self):
        yield self.connection

    connect = connect_task_io


class Facts:
    def __init__(self):
        self.statements = []

    def execute(self, sql, args=()):
        self.statements.append((sql, args))
        if "FROM agent_tasks task" in sql:
            return Row({"task_id": SID})
        if sql.startswith("SET TRANSACTION"):
            return Row(None)
        raise AssertionError(sql)


facts = Facts()
control = NS(deployment_namespace="erpnext", get_in_transaction=Mock(return_value=INSTANCE))
gate = object.__new__(policy.ERPWorkspaceContainment)
gate._database, gate._workspace_control = Database(facts), control
with (
    patch("agent_storage.postgres.task_admission.read_session_task_binding", return_value=BINDING),
    patch("agent_storage.postgres.workspaces.get_workspace_in_transaction") as workspace_read,
):
    for reference in (f"workspace://{WID}", f"workspace:/{WID}"):
        workspace_read.return_value = NS(workspace_root=reference)
        refuses(lambda: gate.require(SID), policy.PRIVATE_NOT_ACTIVATED)
    # Actual native API leaves control owner NULL; only the complete canonical
    # Task/active-Segment/projection/UUID join makes it a private generation.
    control.get_in_transaction.return_value = INSTANCE.model_copy(update={"owner_session_id": None})
    refuses(lambda: gate.require(SID), policy.PRIVATE_NOT_ACTIVATED)
    control.get_in_transaction.return_value = INSTANCE.model_copy(
        update={"owner_session_id": uuid4()}
    )
    refuses(lambda: gate.require(SID), policy.LEGACY_OBSERVATION_ONLY)
    control.get_in_transaction.return_value = INSTANCE
    for reference in (
        "/var/lib/zebra/erpnext-workspaces",
        f"workspace://{WID}/",
        str(WID),
        "unknown",
    ):
        workspace_read.return_value = NS(workspace_root=reference)
        refuses(lambda: gate.require(SID), policy.LEGACY_OBSERVATION_ONLY)
    for state in ("pending", "uncertain", "ready"):
        instance = INSTANCE.model_copy(
            update={
                "state": state,
                "source": INSTANCE.source.model_copy(
                    update={"locator": "/var/lib/zebra/erpnext-workspaces"}
                ),
            }
        )
        control.get_in_transaction.return_value = instance
        workspace_read.return_value = NS(workspace_root=f"workspace://{WID}")
        refuses(lambda: gate.require(SID), policy.LEGACY_OBSERVATION_ONLY)
assert all(
    not sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for sql, _ in facts.statements
)

# Every existing execution entrypoint reaches the same last defense. Use the real
# heartbeat and verify release on refusal, with no setup failure finalizer.
lease = WorkerLease(
    session_id=SID,
    fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="qa"),
    acquired_at=NOW,
    heartbeat_at=NOW,
    expires_at=NOW + timedelta(hours=1),
)
claimed = ClaimedSession(
    lease=lease,
    recovery=NS(session=NS(status=SessionStatus.RUNNING), workspace=NS(), is_terminal=False),
)
claims = NS(
    claim_session=Mock(return_value=claimed),
    recover_lease=Mock(return_value=claimed),
    heartbeat_lease=Mock(return_value=lease),
    release_lease=Mock(),
)
service = object.__new__(execution.SessionExecutionService)
service._erp_workspace_containment = NS(
    require=Mock(side_effect=policy.ERPWorkspacePolicyRefusal(policy.LEGACY_OBSERVATION_ONLY))
)
service._projection_recorder_factory = NS(completion_reader=None)
service._claim_service = claims
service._resume_service = NS(require_resumable=lambda *args, **kwargs: NS(claimed=claimed))
service._execution_namespace = "erpnext"
with ExitStack() as stack:
    forbidden = [
        stack.enter_context(patch.object(module, name, side_effect=AssertionError(name)))
        for module, name in (
            (execution, "recover_execution_progress"),
            (execution, "prepare_execution_inputs"),
            (execution_recovery, "finalize_worker_setup_failure"),
        )
    ]
    for entry in (
        lambda: service.execute_session(SID, worker_id="qa"),
        lambda: service.execute_claimed_session(lease),
        lambda: execution_recovery.execute_claimed_with_stale_retry(
            service, claimed, started_at=NOW, ownership_check=lambda: None
        ),
    ):
        refuses(entry, policy.LEGACY_OBSERVATION_ONLY)
    assert claims.release_lease.call_count == 2
    assert all(check.call_count == 0 for check in forbidden)

# Independent memory path refuses before recorder/finalization/reservation/model.
memory = object.__new__(cloud_memory_recovery.CloudMemoryFinalizationRecovery)
memory._claim_service = claims
memory._erp_workspace_containment = service._erp_workspace_containment
with (
    patch.object(cloud_memory_recovery, "finalize_cloud_memory") as finalize,
    patch.object(cloud_memory_recovery, "_reserve_title_attempt") as reserve,
    patch.object(cloud_memory_recovery, "_mark_memory_recovered") as receipt,
):
    refuses(
        lambda: memory.recover(SID, worker_id="qa", recovered_at=NOW, lease_ttl_seconds=30),
        policy.LEGACY_OBSERVATION_ONLY,
    )
    assert not finalize.called and not reserve.called and not receipt.called
assert claims.release_lease.call_count == 3

# A stale recovery retries through the exact same source policy, never around it.
service._recovery_service = NS(recover_session=Mock(return_value=claimed.recovery))
with (
    patch.object(
        execution,
        "recover_committed_completion",
        side_effect=[execution_recovery.StaleExecutionSnapshot("QA"), None],
    ),
    patch.object(execution, "prepare_execution_inputs") as prepare,
):
    refuses(
        lambda: execution_recovery.execute_claimed_with_stale_retry(
            service, claimed, started_at=NOW, ownership_check=lambda: None
        ),
        policy.LEGACY_OBSERVATION_ONLY,
    )
    assert service._recovery_service.recover_session.call_count == 1 and not prepare.called

# Missing native policy/binding dependencies are a startup error, not an opt-out.
with patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}):
    try:
        execution.SessionExecutionService(
            database_path=None,
            claim_service=claims,
            resume_service=None,
            deployment_namespace="erpnext",
        )
    except ValueError as error:
        assert "requires native" in str(error)
    else:
        raise AssertionError("Missing policy accepted at startup")


# Legacy canonical rejection uses the fingerprint receipt, before append/lease.
class Receipts:
    def __init__(self):
        self.rows = {}

    def get(self, *, action, idempotency_key):
        return self.rows.get((action, idempotency_key))

    def save(self, record):
        self.rows.setdefault((record.action, record.idempotency_key), record)
        return record


receipts = Receipts()
stores = NS(events=Mock(), sessions=Mock(), workspaces=Mock(), idempotency=receipts)
legacy = SessionCommandConsumer(
    stores,
    service,
    command_sessions=lambda *args: [
        NS(session_id=SID, current_sequence=1, status=SessionStatus.READY)
    ],
)
legacy._append_message = Mock(side_effect=AssertionError("MESSAGE"))
legacy._cancel = Mock()
for kind in (
    SessionCommandKind.RUN,
    SessionCommandKind.RESUME,
    SessionCommandKind.MESSAGE,
    SessionCommandKind.STOP,
    SessionCommandKind.CANCEL,
):
    command = SessionCommand(
        session_id=SID,
        kind=kind,
        expected_revision=1,
        idempotency_key=kind.value,
        payload={"content": "QA"} if kind is SessionCommandKind.MESSAGE else {},
    )
    event = SessionEvent.create(
        session_id=SID,
        sequence=2,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )
    legacy._command_reader = lambda *args, event=event: event
    result = legacy.consume_once(worker_id="qa", lease_ttl_seconds=30)
    if kind in {SessionCommandKind.STOP, SessionCommandKind.CANCEL}:
        assert result.status == "executed"
    else:
        assert result.reason == policy.LEGACY_OBSERVATION_ONLY
        assert command_rejected(receipts, event)
        record = next(r for r in receipts.rows.values() if r.idempotency_key == str(event.event_id))
        assert record.status_code == 409
        size = len(receipts.rows)
        legacy.consume_once(worker_id="qa", lease_ttl_seconds=30)
        assert len(receipts.rows) == size
assert legacy._cancel.call_count == 2 and not legacy._append_message.called
assert not stores.events.append.called


# Ready/memory database predicates are applied before LIMIT: no ineligible source
# occupies the candidate batch, including currently unactivated private sources.
class Queries:
    def __init__(self):
        self.sql = []

    def execute(self, sql, args=()):
        self.sql.append(sql)
        return Row(None)


queries = Queries()
store = object.__new__(projections.PostgresProjectionStore)
store._database = Database(queries)
with patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "enabled"}):
    assert store.list_ready_sessions(limit=1) == []
    assert store.list_memory_recovery_sessions(limit=1, recovery_action="qa") == []
    assert all(sql.index("AND FALSE") < sql.index("LIMIT") for sql in queries.sql)
with patch.dict(os.environ, {policy.ERP_CONTAINMENT_ENV: "disabled"}):
    queries.sql.clear()
    store.list_ready_sessions(limit=1)
    assert "AND FALSE" not in queries.sql[0]


check_command_handoff = __import__("legacy_containment_handoff").check_command_handoff

check_command_handoff(Database, NOW, REF, Row, SID, lease)

print(
    "PASS ERP source classification; shared execution and memory refu"
    "sal with real heartbeat release; legacy exact409 receipt and STO"
    "P/CANCEL; SQL candidate exclusion before LIMIT; modern preflight"
    ", idempotent metadata refusal, active/Started/handled/control pr"
    "eservation; disabled compatibility"
)
