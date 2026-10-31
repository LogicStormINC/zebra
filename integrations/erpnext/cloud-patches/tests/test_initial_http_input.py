"""Run with an installed native Python workspace; no DB, S3, model or ERP writes.

This verifies typed staging, grant proof boundaries, row models and native atomic
admission composition. A real disposable PostgreSQL check remains a release gate.
"""

import importlib

import overlay_imports as overlay_imports

# isort: split

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.attachments import TextAttachmentInput
from agent_core.domain.events import EventType
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.http_input_attachments import (
    ConsumedHostGrantProof,
    registry_policy_digest,
)
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
    host_context_digest,
)
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from agent_storage.postgres import task_admission as transaction
from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.http_input_attachments import (
    admit_http_input,
    prepare_http_input,
)
from zebra_agent_api.http_input_attachments import verified_input_authority

NOW = datetime.now(UTC)
registry = dict(
    host_app_id="erpnext",
    namespace_id="erpnext",
    issuer="https://erp.example",
    audience="zebra",
    jwks_uri="https://erp.example/keys",
    allowed_origins=["https://erp.example"],
    algorithms=["RS256"],
    policy_version="v1",
    active=True,
)
context = HostContextEnvelope(
    grant_id="qa-grant",
    host_app_id="erpnext",
    namespace_id="erpnext",
    workspace_ref="private-user-company",
    resource_refs=(
        HostResourceRef(type="thread", id="thread"),
        HostResourceRef(type="principal", id="user"),
    ),
    scopes=("agent.run",),
    limits=HostTechnicalLimits(
        max_runtime_seconds=10, max_model_tokens=1000, max_artifact_bytes=100000
    ),
    origin="https://erp.example",
    policy_version="v1",
    expires_at=NOW + timedelta(minutes=5),
)
proof = ConsumedHostGrantProof(
    deployment_namespace="erpnext",
    grant_id=context.grant_id,
    grant_digest="a" * 64,
    expires_at=context.expires_at,
    authority_issuer=registry["issuer"],
    algorithm="RS256",
    audit_id=1,
    policy_version="v1",
    trust_policy_revision=registry_policy_digest(registry),
)
caps = capability_set(["agent.execute", "evidence.read"])


def binding(task_id):
    return TaskBindingSnapshot(
        task_id=str(task_id),
        agent_capability_ceiling=AgentCapabilityCeilingSnapshot(
            definition_snapshot_digest="b" * 64,
            capability_profile_ref="profile/default@1",
            capabilities=caps,
            resolved_at=NOW,
        ),
        host_capability=HostCapabilitySnapshot(
            host_app_id="erpnext",
            authority_issuer=registry["issuer"],
            namespace_id="erpnext",
            host_context=context,
            grant_digest=host_context_digest(context),
            grant_expires_at=context.expires_at,
            connector_id="erp",
            connector_profile_revision=1,
            connector_profile_digest="c" * 64,
            manifest_digest="d" * 64,
            capabilities=caps,
            resource_binding_digest="e" * 64,
            bound_at=NOW,
        ),
        zebra_policy_digest="f" * 64,
        effective_capabilities=caps,
        binding_revision=1,
        bound_at=NOW,
    )


bootstrap = SessionBootstrapService().build(
    SessionBootstrapCommand(
        title="QA",
        user_input="read files",
        workspace_root="/tmp/http-input-qa",
        host_context=context,
    )
)
raw_event = next(e for e in bootstrap.events if e.event_type is EventType.USER_MESSAGE_RECEIVED)
bound = binding(raw_event.session_id)
verified = VerifiedHostGrant(
    context=context,
    grant_id=context.grant_id,
    algorithm=JwtAlgorithm.RS256,
    authority_issuer=registry["issuer"],
    subject_ref="user",
    consumed_proof=proof,
)
authority = verified_input_authority(verified, bound)


def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("Expected rejection")


class Row:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self):
        self.inserts = []
        self.registry = dict(registry)
        self.now = NOW
        self.evidence = True

    def execute(self, sql, args=()):
        if "FROM host_authority_registries" in sql:
            return Row(self.registry)
        if "FROM host_grant_replay_ledger" in sql:
            if not self.evidence or args[6] != proof.grant_digest:
                return Row(None)

            def digest(values):
                return sha256("\x1f".join(sorted(values)).encode()).hexdigest()

            return Row(
                dict(
                    expires_at=proof.expires_at,
                    scopes_digest=digest(context.scopes),
                    resource_digest=digest(
                        f"{r.resource_type}:{r.resource_id}" for r in context.resource_refs
                    ),
                )
            )
        if "clock_timestamp()" in sql:
            return Row(dict(now=self.now))
        if "INSERT INTO artifact_payload_metadata" in sql:
            self.inserts.append(args)
            return Row(None)
        raise AssertionError(sql)


class Objects:
    def __init__(self):
        self.payloads = {}
        self.puts = 0
        self.fail = False

    def put_if_absent(self, request):
        self.puts += 1
        if self.fail:
            raise ValueError("provider unavailable")
        assert sha256(request.payload).hexdigest() == request.expectation.sha256
        assert len(request.payload) == request.expectation.size_bytes
        self.payloads[request.expectation.artifact_id] = request.payload
        return ArtifactObjectReceipt(
            expectation=request.expectation, object_version="v1", verified_at=NOW
        )

    def verify(self, expectation):
        return SimpleNamespace(receipt=None)


objects = Objects()
inputs = tuple(
    TextAttachmentInput(file_name=f"{n}.txt", media_type="text/plain", payload=f"file-{n}".encode())
    for n in range(4)
)
event, batch = prepare_http_input(objects, "erpnext", authority, raw_event, inputs)
c = Connection()
admit_http_input(c, "erpnext", batch, event, bound)
assert len(c.inserts) == 4 and len(objects.payloads) == 4
assert all(e.reference.message_event_id == event.event_id for e in batch.entries)
assert "content_base64" not in str(event.payload) and "file-0" not in str(event.payload)
rejects(lambda: verified_input_authority(replace(verified, consumed_proof=None), bound))
rejects(lambda: prepare_http_input(objects, "erpnext", authority, raw_event, inputs + (inputs[0],)))
rejects(
    lambda: prepare_http_input(objects, "erpnext", authority, raw_event, (inputs[0], inputs[0]))
)
for alter in ("registry", "expiry", "evidence", "binding", "grant", "principal"):
    c = Connection()
    auth = authority
    target = bound
    if alter == "registry":
        c.registry["active"] = False
    if alter == "expiry":
        c.now = proof.expires_at + timedelta(seconds=1)
    if alter == "evidence":
        c.evidence = False
    if alter == "binding":
        target = bound.model_copy(update={"binding_revision": 2})
    if alter == "grant":
        auth = authority.model_copy(
            update={"proof": proof.model_copy(update={"grant_digest": "0" * 64})}
        )
    if alter == "principal":
        auth = authority.model_copy(
            update={
                "context": context.model_copy(
                    update={
                        "resource_refs": (
                            HostResourceRef(type="thread", id="thread"),
                            HostResourceRef(type="principal", id="other"),
                        )
                    }
                )
            }
        )
    rejects(
        lambda *, auth=auth, c=c, target=target: admit_http_input(
            c, ("erpnext"), replace(batch, authority=auth), event, target
        )
    )
    assert c.inserts == []
objects.fail = True
rejects(
    lambda: prepare_http_input(
        objects,
        "erpnext",
        authority,
        raw_event,
        (TextAttachmentInput(file_name="fail.txt", media_type="text/plain", payload=b"fail"),),
    )
)
objects.fail = False
entry = batch.entries[0]
ref = entry.reference
request = entry.reservation
row = dict(
    deployment_namespace="erpnext",
    artifact_id=ref.attachment_id,
    session_id=event.session_id,
    intended_event_sequence=event.sequence,
    kind=request.kind,
    mime_type=request.mime_type,
    sha256=ref.sha256,
    size_bytes=ref.size_bytes,
    idempotency_key=request.idempotency_key,
    file_name=ref.file_name,
    retained_until=None,
    request_created_at=request.created_at,
    object_version="v1",
    object_verified_at=NOW,
    event_id=event.event_id,
    event_sequence=event.sequence,
    artifact_uri=f"artifact://{ref.attachment_id}",
    lifecycle_status="finalized",
    lifecycle_revision=0,
    finalized_at=NOW,
    compensated_at=None,
    pruning_at=None,
    pruned_at=None,
    authority_kind="http_input",
    http_input_authority=authority.model_dump(mode="json"),
    reservation_epoch=None,
    reservation_fencing_token=None,
    reservation_owner_instance_id=None,
)
assert artifact_payload_from_row(row).authority_kind == "http_input"
for lifecycle in ("pruning", "pruned"):
    assert (
        artifact_payload_from_row(
            dict(
                row,
                lifecycle_status=lifecycle,
                pruning_at=NOW,
                pruned_at=NOW if lifecycle == "pruned" else None,
            )
        ).authority_kind
        == "http_input"
    )
for bad in (
    dict(row, authority_kind="unknown"),
    dict(row, reservation_fencing_token=1),
    dict(row, http_input_authority=None),
    dict(row, lifecycle_status="staged"),
):
    rejects(lambda bad=bad: artifact_payload_from_row(bad))
worker = dict(
    row,
    authority_kind="worker",
    http_input_authority=None,
    reservation_epoch=uuid4(),
    reservation_fencing_token=1,
    reservation_owner_instance_id="real-worker",
)
assert artifact_payload_from_row(worker).authority_kind == "worker"
rejects(lambda: artifact_payload_from_row(dict(worker, reservation_fencing_token=None)))

# Execute the actual admission orchestration with a single caller transaction;
# doubles replace SQL helpers, not the Core validation or HTTP input hook.
request = TaskAdmissionRequest(
    events=tuple(event if e.event_id == event.event_id else e for e in bootstrap.events),
    session=bootstrap.session,
    workspace=rebuild_workspace(list(bootstrap.events)),
    binding=bound,
    http_input=batch,
)
seen = []
saved = {}
patches = {
    "append_event_in_transaction": lambda conn, namespace, event: seen.append(("event", conn))
    or event,
    "save_session_in_transaction": lambda conn, *args: seen.append(("session", conn)),
    "save_workspace_in_transaction": lambda conn, *args: seen.append(("workspace", conn)),
    "rebuild_task_in_transaction": lambda conn, *args: seen.append(("task", conn))
    or SimpleNamespace(task_id=event.session_id),
    "_insert_binding_snapshot": lambda conn, *args: seen.append(("binding", conn))
    or bound.binding_digest,
}
for name, value in patches.items():
    saved[name] = getattr(transaction, name)
    setattr(transaction, name, value)
c = Connection()
try:
    service = object.__new__(transaction.PostgresTaskAdmissionTransaction)
    receipt = service.admit_in_transaction(c, "erpnext", request)
    assert receipt.event_count == len(request.events) and len(c.inserts) == 4
    assert {id(conn) for _, conn in seen} == {id(c)}
    assert [name for name, _ in seen].index("binding") < len(seen)
finally:
    for name, value in saved.items():
        setattr(transaction, name, value)

# Native create_session replay returns before parsing/staging another batch.
api_module = importlib.import_module("zebra_agent_api.app")
request_hash = __import__("zebra_agent_api.idempotency", fromlist=("request_hash",)).request_hash

payload = {
    "prompt": "read files",
    "attachments": [{"file_name": "a.txt", "media_type": "text/plain", "content_base64": "YQ=="}],
}
stored = SimpleNamespace(
    request_hash=request_hash(payload), status_code=201, response_body={"session_id": "original"}
)
original = api_module.reconcile_replayed_run
api_module.reconcile_replayed_run = lambda app, response, *args: response
try:
    fake = SimpleNamespace(
        stores=SimpleNamespace(idempotency=SimpleNamespace(get=lambda **kwargs: stored))
    )
    puts = objects.puts
    replay = api_module.ZebraAgentApi.create_session(
        fake, payload, idempotency_key="same", host_context=context
    )
    assert replay.body == {"session_id": "original"} and objects.puts == puts
finally:
    api_module.reconcile_replayed_run = original
print(
    "PASS initial HTTP input: four files, verified proof failures, st"
    "rict read lanes, one native transaction, zero-put completed repl"
    "ay"
)

# Real initial queue adapter forwards the exact prepared batch into admission,
# and rejects missing proof/provider failure before any canonical admission.
TaskAdmissionReceipt = __import__(
    "agent_core.ports.task_admission_transaction", fromlist=("TaskAdmissionReceipt",)
).TaskAdmissionReceipt
queue = __import__("zebra_agent_api", fromlist=("session_queue",)).session_queue
parse_create_session_payload = __import__(
    "zebra_agent_api.session_payloads", fromlist=("parse_create_session_payload",)
).parse_create_session_payload

parsed = parse_create_session_payload(
    dict(
        title="QA",
        prompt="read",
        workspace="/tmp/http-input-qa",
        attachments=[dict(file_name="a.txt", media_type="text/plain", content_base64="YQ==")],
    )
)
assert isinstance(parsed, dict)
old_derive = queue._derive_binding
old_admit = transaction.PostgresTaskAdmissionTransaction.admit
captured = []


class Prepared:
    def prepare(self, authority, binding, event, attachments):
        assert authority.binding_digest == binding.binding_digest
        return prepare_http_input(objects, "erpnext", authority, event, attachments)


queue._derive_binding = lambda session_id, **kwargs: binding(session_id)


def accept(self, request):
    captured.append(request)
    assert request.http_input.session_id == request.session.session_id
    return TaskAdmissionReceipt(
        task_id=request.session.session_id,
        session_id=request.session.session_id,
        event_count=len(request.events),
        binding_digest=request.binding.binding_digest,
    )


transaction.PostgresTaskAdmissionTransaction.admit = accept
try:
    stores = SimpleNamespace(http_input_admission=Prepared())
    response = queue.create_queued_session(
        stores,
        parsed,
        host_context=context,
        verified_host_grant=verified,
        admission_dsn="not-opened",
        admission_namespace="erpnext",
        idempotency_key="queue-key",
        idempotency_request_hash="a" * 64,
    )
    assert response.status_code == 201 and len(captured) == 1
    assert response.body["attachments"][0]["sha256"] == sha256(b"a").hexdigest()
    before = objects.puts
    denied = queue.create_queued_session(
        stores,
        parsed,
        host_context=context,
        verified_host_grant=replace(verified, consumed_proof=None),
        admission_dsn="not-opened",
        admission_namespace="erpnext",
    )
    assert denied.status_code == 403 and objects.puts == before and len(captured) == 1
    objects.fail = True
    failed = queue.create_queued_session(
        stores,
        parsed,
        host_context=context,
        verified_host_grant=verified,
        admission_dsn="not-opened",
        admission_namespace="erpnext",
    )
    assert failed.status_code == 503 and len(captured) == 1
finally:
    queue._derive_binding = old_derive
    transaction.PostgresTaskAdmissionTransaction.admit = old_admit
    objects.fail = False
print(
    "PASS real queued-Task adapter: canonical batch forwarding and pr"
    "e-admission proof/provider failure"
)
