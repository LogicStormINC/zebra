"""Exact API105 + overlay, disposable PG: actual AG-UI handler/renewal/admission.

No HTTP auth server, model or business execution is claimed. Native Worker Event
commits below are deterministic test evidence for the prior-gate regression.
"""

from copy import deepcopy
from types import SimpleNamespace as Simple

from agent_core.application.session_projection import rebuild_session
from agent_core.domain.identifiers import TaskId
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.command_wakeup_outcome import PostgresCommandOutcomeReader
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.projections import PostgresProjectionStore
from agent_storage.postgres.task_admission import load_task_binding
from agent_storage.postgres.workspaces import PostgresWorkspaceProjectionStore
from check_fresh_refusal_postgres import (
    DSN as DSN,
)
from check_fresh_refusal_postgres import (
    NS as NS,
)
from check_fresh_refusal_postgres import (
    EventActor as EventActor,
)
from check_fresh_refusal_postgres import (
    EventType as EventType,
)
from check_fresh_refusal_postgres import (
    HandoffStatus as HandoffStatus,
)
from check_fresh_refusal_postgres import (
    HostResourceRef as HostResourceRef,
)
from check_fresh_refusal_postgres import (
    Jsonb as Jsonb,
)
from check_fresh_refusal_postgres import (
    PrincipalScope as PrincipalScope,
)
from check_fresh_refusal_postgres import (
    SessionEvent as SessionEvent,
)
from check_fresh_refusal_postgres import (
    accepted as accepted,
)
from check_fresh_refusal_postgres import (
    classic as classic,
)
from check_fresh_refusal_postgres import (
    db as db,
)
from check_fresh_refusal_postgres import (
    disposition as disposition,
)
from check_fresh_refusal_postgres import (
    events as events,
)
from check_fresh_refusal_postgres import (
    handoff_command as handoff_command,
)
from check_fresh_refusal_postgres import (
    leases as leases,
)
from check_fresh_refusal_postgres import (
    read as read,
)
from check_fresh_refusal_postgres import (
    rebuild_workspace as rebuild_workspace,
)
from check_fresh_refusal_postgres import (
    rejected as rejected,
)
from check_fresh_refusal_postgres import (
    seal as seal,
)
from check_fresh_refusal_postgres import (
    temporary as temporary,
)
from check_fresh_refusal_postgres import (
    timedelta as timedelta,
)
from check_fresh_refusal_postgres import (
    uuid4 as uuid4,
)
from zebra_agent_api.ag_ui_checkpoint_tail import observation_problem
from zebra_agent_api.ag_ui_command import handle_agui_command
from zebra_agent_api.api_command_mixin import ApiCommandMixin
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.session_binding import renew_host_binding_for_command
from zebra_agent_api.task_api import TaskReadApi

snapshots = PostgresExtensionSnapshotStore(DSN, deployment_namespace=NS)
extensions = CloudExtensionTurnAdmission(
    PostgresExtensionStore(DSN, deployment_namespace=NS), snapshots, snapshots
)

stores = Simple(
    events=events,
    sessions=PostgresProjectionStore(DSN, deployment_namespace=NS),
    tasks=PostgresAgentTaskStore(DSN, deployment_namespace=NS),
    workspaces=PostgresWorkspaceProjectionStore(DSN, deployment_namespace=NS),
    deployment_namespace=NS,
)


class App(ApiCommandMixin):
    pass


app = App()
app.stores = stores
app.settings = Simple(
    deployment="cloud",
    storage_authority="postgresql",
    database_url=DSN,
    stream=Simple(capacity_policy=None, new_admission_enabled=False),
)
reader = PostgresCommandOutcomeReader(DSN, deployment_namespace=NS)


def grant(sid, run):
    binding = load_task_binding(DSN, deployment_namespace=NS, task_id=TaskId(sid))
    original = binding.host_capability.host_context
    context = original.model_copy(
        update={
            "grant_id": str(uuid4()),
            "resource_refs": tuple(r for r in original.resource_refs if r.resource_type != "run")
            + (HostResourceRef(type="run", id=run),),
        }
    )
    return VerifiedHostGrant(
        context=context,
        grant_id=context.grant_id,
        algorithm=JwtAlgorithm.RS256,
        authority_issuer=binding.host_capability.authority_issuer,
        subject_ref="qa-owner",
    )


def command(sid, verified, revision, key):
    return handle_agui_command(
        app,
        Simple(
            method="POST",
            path="/agui/commands",
            body={
                "action": "run",
                "threadId": str(sid),
                "runId": next(
                    r.resource_id
                    for r in verified.context.resource_refs
                    if r.resource_type == "run"
                ),
                "expectedRevision": revision,
                "input": {"messages": []},
            },
            headers={"Idempotency-Key": key},
            verified_host_grant=verified,
        ),
        extension_admission=extensions,
    )


def worker_event(lease, kind, payload):
    prior = events.list_for_session(lease.session_id)
    # Native projection replay of admitted metadata precedes Worker events,
    # just as claim recovery catches an unprojected command up to the stream.
    stores.sessions.save_session(rebuild_session(prior))
    stores.workspaces.save_workspace(rebuild_workspace(prior))
    e = SessionEvent.create(
        session_id=lease.session_id,
        sequence=prior[-1].sequence + 1,
        event_type=kind,
        actor=EventActor.HARNESS,
        payload=payload,
    )
    stream = [*prior, e]
    stores.workspaces.commit_worker_event(
        e,
        rebuild_session(stream),
        rebuild_workspace(stream),
        authority=WorkerMutationAuthority(
            deployment_namespace=NS,
            session_id=lease.session_id,
            expected_stream_revision=prior[-1].sequence,
            lease_fence=lease.fence,
        ),
    )
    stores.tasks.ensure_for_session(lease.session_id)
    return e


# Classic seal corruption must not pass merely because its legacy rejection exists.
original = read(classic, True)
for corruption in [
    None,
    {},
    dict(original["fence"], fencing_token=0),
    dict(original["fence"], owner_instance_id=""),
    dict(original["fence"], fencing_token=original["fence"]["fencing_token"] + 1),
]:
    damaged = deepcopy(original)
    if corruption is None:
        damaged.pop("fence")
    else:
        damaged["fence"] = corruption
    with db.connect() as c:
        c.execute(
            (
                "UPDATE control_plane_idempotency_records SET response_body=%s WH"
                "ERE deployment_namespace=%s AND action=%s AND idempotency_key=%s"
            ),
            (Jsonb(damaged), NS, disposition.ACTION, f"{classic.event_id}:0"),
        )
    rejected(lambda: read(classic, True))
with db.connect() as c:
    c.execute(
        (
            "UPDATE control_plane_idempotency_records SET response_body=%s WH"
            "ERE deployment_namespace=%s AND action=%s AND idempotency_key=%s"
        ),
        (Jsonb(original), NS, disposition.ACTION, f"{classic.event_id}:0"),
    )
assert read(classic, True) == original
print("PASS PG classic missing/malformed/valid-but-changed historical fence rejected")

for mode in ["classic", "modern", "exhausted"]:
    if mode == "classic":
        prior = classic
        sid = classic.session_id
        proof = original
    elif mode == "exhausted":
        prior = temporary
        sid = temporary.session_id
        proof = read(temporary, True)
    else:
        sid, prior, scope, lease = accepted()
        proof = seal(lease)
        leases.release(sid, fence=lease.fence)
    scope = PrincipalScope(kind="principal", tenant_id=NS, workspace_id=proof["workspace_id"])
    priorgrant = grant(sid, proof["run_id"])
    stores.tasks.ensure_for_session(sid)
    outcome = reader.fresh_header_outcome(TaskId(sid), priorgrant.context)
    assert outcome["retry_eligible"] and outcome["accepted_event_id"] == str(prior.event_id)
    header = TaskReadApi(stores).header(
        str(sid), host_context=priorgrant.context, command_outcome=reader
    )
    assert (
        header.status_code == 200
        and header.body["status"] == "ready"
        and header.body["command_outcome"] == outcome
    )
    wrong = priorgrant.context.model_copy(update={"workspace_ref": "other-workspace"})
    rejected(lambda *, sid=sid, wrong=wrong: reader.fresh_header_outcome(TaskId(sid), wrong))
    assert "zebra.observation.problem" in observation_problem(outcome["code"], retryable=False)
    new = grant(sid, str(uuid4()))
    key = str(uuid4())
    revision = events.list_for_session(sid)[-1].sequence
    response = command(sid, new, revision, key)
    assert response.status_code == 202, (response.status_code, response.body)
    renewed = grant(sid, new.context.resource_refs[-1].resource_id)
    assert renewed.grant_id != new.grant_id
    replay = command(sid, renewed, revision, key)
    assert replay.status_code == 200, (replay.status_code, replay.body)
    after = events.list_for_session(sid)
    successor = after[-1]
    assert successor.event_type is EventType.SESSION_COMMAND_ACCEPTED
    assert sum(e.event_type is EventType.USER_MESSAGE_RECEIVED for e in after) == 1
    assert successor.payload["payload"]["input"]["messages"] == []
    extension_digest = successor.payload["extension_snapshot_digest"]
    assert successor.payload["extension_turn_id"] == proof["turn_id"]
    # A second explicit retry of the same never-started Turn must reuse the
    # actual server-owned snapshot, not silently choose new live extensions.
    scope2, snapshot2, ceiling2 = extensions.prepare(
        verified=renewed, session_id=sid, events=after, client_payload={}, existing_turn=True
    )
    assert snapshot2.digest == extension_digest
    picked = handoff_command(
        DSN,
        deployment_namespace=NS,
        scope=scope,
        accepted_event_id=successor.event_id,
        owner_instance_id="qa-successor",
        ttl=timedelta(seconds=60),
    )
    assert picked.status is HandoffStatus.ACCEPTED, picked.status
    assert read(prior, True) == proof  # historical fence is independent of successor lease
    # Prove a started successor never receives a no-effect rewrite.
    worker_event(picked.lease, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    rejected(lambda *, picked=picked: seal(picked.lease))
    worker_event(
        picked.lease,
        EventType.TURN_COMPLETED,
        {
            "turn_id": proof["turn_id"],
            "turn_index": proof["turn_index"],
            "summary": "QA metadata fixture",
            "closes_segment": False,
        },
    )
    leases.release(sid, fence=picked.lease.fence)
    assert read(prior, True) == proof
    third = grant(sid, str(uuid4()))
    assert renew_host_binding_for_command(app, str(sid), third) is None
    revision = events.list_for_session(sid)[-1].sequence
    admitted = app.submit_command(
        str(sid),
        {
            "kind": "message",
            "expected_revision": revision,
            "payload": {
                "content": "new explicit human Turn",
                "thread_id": str(sid),
                "run_id": next(
                    r.resource_id for r in third.context.resource_refs if r.resource_type == "run"
                ),
            },
        },
        idempotency_key=str(uuid4()),
        extension_admission=extensions,
        verified_host_grant=third,
    )
    assert admitted.status_code == 202, (admitted.status_code, admitted.body)
    message = events.list_for_session(sid)[-1]
    third_pick = handoff_command(
        DSN,
        deployment_namespace=NS,
        scope=scope,
        accepted_event_id=message.event_id,
        owner_instance_id="qa-third-message",
        ttl=timedelta(seconds=60),
    )
    assert third_pick.status is HandoffStatus.ACCEPTED, third_pick.status
    assert read(prior, True) == proof
    leases.release(sid, fence=third_pick.lease.fence)
print(
    "PASS configured native CloudExtensionTurnAdmission/same-Turn sna"
    "pshot reuse/new-Turn snapshot; actual AG-UI handler/new Grant bi"
    "nding renewal/empty-message RUN/idempotent lostACK; header+scope"
    "; native started negative; third ordinary MESSAGE after successo"
    "r completion for classic/permanent/exhausted"
)
