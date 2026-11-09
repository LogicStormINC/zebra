"""Native105 disposable PG: real process attestation and strict authority pins.

Only synthetic strict ERP metadata with the extra native history scopes is used.
This does not enable strict ERP execution or contact Host/model/business endpoints.
"""

from time import sleep

from check_fresh_refusal_postgres import (
    DSN as DSN,
)
from check_fresh_refusal_postgres import (
    NS as NS,
)
from check_fresh_refusal_postgres import (
    UTC as UTC,
)
from check_fresh_refusal_postgres import (
    HandoffStatus as HandoffStatus,
)
from check_fresh_refusal_postgres import (
    database_name as database_name,
)
from check_fresh_refusal_postgres import (
    datetime as datetime,
)
from check_fresh_refusal_postgres import (
    db as db,
)
from check_fresh_refusal_postgres import (
    disposition as disposition,
)
from check_fresh_refusal_postgres import (
    handoff_command as handoff_command,
)
from check_fresh_refusal_postgres import (
    leases as leases,
)
from check_fresh_refusal_postgres import (
    patch as patch,
)
from check_fresh_refusal_postgres import (
    read as read,
)
from check_fresh_refusal_postgres import (
    setup as setup,
)
from check_fresh_refusal_postgres import (
    timedelta as timedelta,
)
from check_fresh_refusal_postgres import (
    uuid4 as uuid4,
)

assert database_name == "erpnext_fresh_refusal_106_20261024", (
    "strict current-overlay schema requires the separate reviewed QA106"
)
semantic_check = __import__(
    "agent_core.application.coverage_semantic", fromlist=("semantic_check",)
).semantic_check
CoverageContract = __import__(
    "agent_core.domain.coverage_contracts", fromlist=("CoverageContract",)
).CoverageContract
CoverageScope = __import__(
    "agent_core.domain.coverage_contracts", fromlist=("CoverageScope",)
).CoverageScope
CoverageExecutionBudget = __import__(
    "agent_core.domain.coverage_execution", fromlist=("CoverageExecutionBudget",)
).CoverageExecutionBudget
CoverageTaskAdmission = __import__(
    "agent_core.domain.coverage_task_admission", fromlist=("CoverageTaskAdmission",)
).CoverageTaskAdmission
HostRegistryRecord = __import__(
    "agent_storage.postgres.host_auth", fromlist=("HostRegistryRecord",)
).HostRegistryRecord
PostgresHostAuthorityStore = __import__(
    "agent_storage.postgres.host_auth", fromlist=("PostgresHostAuthorityStore",)
).PostgresHostAuthorityStore
PostgresWorkerCapabilities = __import__(
    "agent_storage.postgres.worker_capability", fromlist=("PostgresWorkerCapabilities",)
).PostgresWorkerCapabilities
WorkerCapabilityLostError = __import__(
    "agent_storage.postgres.worker_capability", fromlist=("WorkerCapabilityLostError",)
).WorkerCapabilityLostError

PostgresHostAuthorityStore(DSN, deployment_namespace=NS).upsert_registry(
    HostRegistryRecord(
        host_app_id=NS,
        namespace_id=NS,
        issuer="https://erp.example.test",
        audience="qa",
        jwks_uri="https://erp.example.test/jwks",
        allowed_origins=("https://erp.example.test",),
        algorithms=("RS256",),
        policy_version="v1",
    )
)
now = datetime.now(UTC)
coverage = CoverageTaskAdmission(
    contract=CoverageContract(
        scope=CoverageScope(
            timezone="UTC", from_inclusive=now - timedelta(days=1), to_exclusive=now
        ),
        checks=(semantic_check("qa/model").contract_check,),
    ),
    history_ref="qa-history",
    model_profile="qa/model",
    execution_budget=CoverageExecutionBudget(max_attempts=1, max_input_bytes=1000),
    max_model_calls=1,
    max_model_tokens=1000,
    max_runtime_seconds=600,
)
capabilities = PostgresWorkerCapabilities(DSN, deployment_namespace=NS)
digest = "1" * 64


def strict_fixture(*, admission=None, host_expiry=None):
    cap = capabilities.register(uuid4(), configuration_digest=digest, ttl_seconds=30)
    sid, event, scope = setup(
        coverage=admission or coverage, configuration_digest=digest, host_expiry=host_expiry
    )
    picked = handoff_command(
        DSN,
        deployment_namespace=NS,
        scope=scope,
        accepted_event_id=event.event_id,
        owner_instance_id="qa-strict",
        ttl=timedelta(seconds=60),
        consumer_capability=cap,
    )
    assert picked.status is HandoffStatus.ACCEPTED
    return sid, event, picked.lease, cap


def strict_seal(lease, cap):
    return disposition.persist_fresh_disposition(
        DSN, NS, lease, consumer_capability=cap, code=disposition.REFUSED, reason="probe_rejected"
    )


def cap_rejected(action):
    try:
        action()
    except WorkerCapabilityLostError:
        return
    raise AssertionError("expected strict process authority refusal")


def unchanged(event):
    with db.connect() as c:
        assert (
            c.execute(
                (
                    "SELECT 1 FROM control_plane_idempotency_records WHERE deployment"
                    "_namespace=%s AND action=%s AND idempotency_key=%s"
                ),
                (NS, disposition.ACTION, f"{event.event_id}:0"),
            ).fetchone()
            is None
        )
        assert c.execute(
            (
                "SELECT status,recovery_code FROM session_command_pending WHERE d"
                "eployment_namespace=%s AND accepted_event_id=%s"
            ),
            (NS, event.event_id),
        ).fetchone() == {"status": "pending", "recovery_code": None}
        receipt = c.execute(
            (
                "SELECT started_event_id,handled_event_id FROM command_handoff_re"
                "ceipts WHERE deployment_namespace=%s AND accepted_event_id=%s"
            ),
            (NS, event.event_id),
        ).fetchone()
        assert receipt == {"started_event_id": None, "handled_event_id": None}


sid, event, lease, cap = strict_fixture()
cap_rejected(lambda: strict_seal(lease, None))
unchanged(event)
proof = strict_seal(lease, cap)
assert read(event, True) == proof
leases.release(sid, fence=lease.fence)
print(
    "PASS native strict actual process attestation seal; missing capa"
    "bility denied; ordinary None covered by inherited checks"
)

sid, event, lease, cap = strict_fixture()
# Naturally expire the actual local process registration after tentative proof
# insertion. The helper remains real; only the transaction delay is injected.
cap = capabilities.heartbeat(cap, configuration_digest=digest, ttl_seconds=2)
original_save = disposition.save_idempotency_in_transaction


def delayed_save(connection, namespace, record):
    stored = original_save(connection, namespace, record)
    if record.action == disposition.ACTION:
        sleep(2.1)  # Native SQL timeout remains unchanged; expire wall-clock authority.
    return stored


with patch.object(disposition, "save_idempotency_in_transaction", delayed_save):
    cap_rejected(lambda: strict_seal(lease, cap))
unchanged(event)
leases.release(sid, fence=lease.fence)
print(
    "PASS native strict natural process capability expiry at final re"
    "pin rolls back proof and pending mutation"
)

# A native current Host expiry still fails strict _identity; no special metadata
# bypass or synthetic prior execution journal is introduced by this slice.
cap = capabilities.register(uuid4(), configuration_digest=digest, ttl_seconds=30)
sid, event, scope = setup(
    coverage=coverage,
    configuration_digest=digest,
    host_expiry=datetime.now(UTC) + timedelta(seconds=3),
)
picked = handoff_command(
    DSN,
    deployment_namespace=NS,
    scope=scope,
    accepted_event_id=event.event_id,
    owner_instance_id="qa-strict-expiry",
    ttl=timedelta(seconds=60),
    consumer_capability=cap,
)
assert picked.status is HandoffStatus.ACCEPTED
with db.connect() as c:
    c.execute("SELECT pg_sleep(3.1)")
cap_rejected(lambda: strict_seal(picked.lease, cap))
unchanged(event)
leases.release(sid, fence=picked.lease.fence)
print(
    "PASS native strict expired Host authority remains unsealed/reconciliation-only; no relaxed pin"
)

# The authorized public reader uses its actual RR READ ONLY transaction. Native
# current strict authority can expire without invalidating a historical seal.
TaskId = __import__("agent_core.domain.identifiers", fromlist=("TaskId",)).TaskId
PostgresCommandOutcomeReader = __import__(
    "agent_storage.postgres.command_wakeup_outcome", fromlist=("PostgresCommandOutcomeReader",)
).PostgresCommandOutcomeReader
load_task_binding = __import__(
    "agent_storage.postgres.task_admission", fromlist=("load_task_binding",)
).load_task_binding

reader = PostgresCommandOutcomeReader(DSN, deployment_namespace=NS)
for deadline in ["host", "runtime"]:
    sid, event, lease, cap = strict_fixture(
        admission=coverage.model_copy(update={"max_runtime_seconds": 3})
        if deadline == "runtime"
        else coverage,
        host_expiry=datetime.now(UTC) + timedelta(seconds=3) if deadline == "host" else None,
    )
    proof = strict_seal(lease, cap)
    leases.release(sid, fence=lease.fence)
    context = load_task_binding(
        DSN, deployment_namespace=NS, task_id=TaskId(sid)
    ).host_capability.host_context
    assert reader.fresh_header_outcome(TaskId(sid), context)["retry_eligible"] is True
    sleep(3.1)
    assert reader.fresh_header_outcome(TaskId(sid), context)["retry_eligible"] is False
    assert read(event, True) == proof
print(
    "PASS actual read-only header strict Host/runtime expiry disables"
    " current retry while immutable historical proof survives"
)
