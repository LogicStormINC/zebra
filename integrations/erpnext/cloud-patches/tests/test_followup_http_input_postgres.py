"""Real native follow-up/clarification/atomic rollover checks in an EMPTY QA DB.

Set ZEBRA_HTTP_INPUT_QA_DSN to a fresh zebra_http_input_qa_* database. No Worker
or model runs here. Existing production/shared databases are explicitly refused.
"""

import overlay_imports as overlay_imports

# isort: split

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import test_initial_http_input as f
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService, current_turn
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres import session_handoff_transactions as handoff
from agent_storage.postgres.host_auth import (
    HostGrantAttempt,
    HostRegistryRecord,
    PostgresHostAuthorityStore,
)
from agent_storage.postgres.migration_runner import (
    apply_postgres_migrations,
    require_current_schema,
)
from agent_storage.postgres.session_handoffs import PostgresSessionHandoffStore
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres_composition import postgres_control_plane_stores
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.http_input_attachments import append_cloud_input as append_cloud_input
from zebra_agent_api.task_api import append_task_message
from zebra_agent_worker.task_recovery import recover_task

DSN = os.environ.get("ZEBRA_HTTP_INPUT_QA_DSN")
if not DSN:
    raise SystemExit("Set ZEBRA_HTTP_INPUT_QA_DSN to a fresh zebra_http_input_qa_* database")
with psycopg.connect(DSN) as c:
    assert c.execute("SELECT current_database()").fetchone()[0].startswith("zebra_http_input_qa_")
    assert (
        c.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
        ).fetchone()[0]
        == 0
    )
apply_postgres_migrations(DSN)
require_current_schema(DSN)
NAMESPACE = "erpnext"
bootstrap_control_plane_epoch(DSN, deployment_namespace=NAMESPACE)
authorizer = PostgresHostAuthorityStore(DSN, deployment_namespace=NAMESPACE)
registry = HostRegistryRecord(**f.registry)
authorizer.upsert_registry(registry)
objects = f.Objects()
# Existing verified Cloud readers require these object-version methods.
objects.read_version_verified = lambda expectation, version: objects.payloads[
    expectation.artifact_id
]
objects.read_verified = lambda expectation: objects.payloads[expectation.artifact_id]
stores = postgres_control_plane_stores(
    DSN,
    deployment_namespace=NAMESPACE,
    memory_cursor_signing_key=b"q" * 32,
    artifact_objects=objects,
    history_scope=OpaqueAuthorityScope(
        authority_issuer=registry.issuer, namespace_id="erpnext-history"
    ),
    continuation_scope=OpaqueAuthorityScope(
        authority_issuer=registry.issuer, namespace_id="erpnext-continuation"
    ),
)
app = SimpleNamespace(
    stores=stores,
    database_path=Path("/tmp/http-input-followup-qa"),
    _parse_session_id=ZebraAgentApi._parse_session_id,
)


def verified():
    context = f.context.model_copy(
        update={"grant_id": str(uuid4()), "expires_at": datetime.now(UTC) + timedelta(minutes=10)}
    )

    def digest(values):
        return f.sha256("\x1f".join(sorted(values)).encode()).hexdigest()

    attempt = HostGrantAttempt(
        issuer=registry.issuer,
        jti=context.grant_id,
        host_app_id=context.host_app_id,
        namespace_id=context.namespace_id,
        algorithm="RS256",
        grant_digest=f.sha256(context.grant_id.encode()).hexdigest(),
        scopes_digest=digest(context.scopes),
        resource_digest=digest(f"{r.resource_type}:{r.resource_id}" for r in context.resource_refs),
        expires_at=context.expires_at,
    )
    accepted = authorizer.consume_grant(attempt, expected_registry=registry)
    assert accepted.accepted
    proof = f.proof.model_copy(
        update={
            "grant_id": context.grant_id,
            "grant_digest": attempt.grant_digest,
            "expires_at": context.expires_at,
            "audit_id": accepted.audit.audit_id,
        }
    )
    return VerifiedHostGrant(
        context=context,
        grant_id=context.grant_id,
        algorithm=JwtAlgorithm.RS256,
        authority_issuer=registry.issuer,
        subject_ref="user",
        consumed_proof=proof,
    )


def seed(kind="ready", profile="deepseek-v4-flash-executor-v1"):
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="QA source",
            user_input="original input",
            workspace_root="/tmp/http-input-source",
            host_context=f.context,
            model_profile=profile,
            reasoning_effort="high",
        )
    )
    sid = boot.session.session_id
    PostgresTaskAdmissionTransaction(DSN, deployment_namespace=NAMESPACE).admit(
        TaskAdmissionRequest(
            events=tuple(boot.events),
            session=boot.session,
            workspace=rebuild_workspace(list(boot.events)),
            binding=f.binding(sid),
        )
    )
    events = list(boot.events)

    def add(event_type, payload):
        event = SessionEvent.create(
            session_id=sid,
            sequence=len(events),
            event_type=event_type,
            actor=EventActor.HARNESS,
            payload=payload,
        )
        stores.events.append(event)
        events.append(event)

    add(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    if kind == "waiting":
        add(
            EventType.CLARIFICATION_REQUESTED,
            dict(
                clarification_id="qa-clar",
                tool_call_id="qa-call",
                question="Which?",
                assistant_message="Choose",
                choices=["yes", "no"],
                attempt_number=1,
                conversation=[],
                model_calls_used=1,
                tool_calls_executed=0,
            ),
        )
    else:
        turn = current_turn(events)
        add(
            EventType.TURN_COMPLETED,
            dict(turn_id=turn.turn_id, turn_index=0, closes_segment=kind == "terminal"),
        )
        if kind == "terminal":
            add(EventType.SESSION_COMPLETED, {"summary": "fixture completed"})
    stores.sessions.save_session(rebuild_session(events))
    stores.workspaces.save_workspace(rebuild_workspace(events))
    stores.tasks.ensure_for_session(sid)
    if kind == "terminal":
        lease = stores.leases.acquire(
            sid, owner_instance_id="qa-source-worker", ttl=timedelta(minutes=1)
        )
        stores.leases.release(sid, fence=lease.fence)
    return TaskId(sid), tuple(events)


def send(task, key, *, content="follow up", clarification_id=None):
    body = dict(
        content=content,
        model_profile="deepseek-v4-flash-executor-v1",
        reasoning_effort="high",
        attachments=[
            dict(file_name="follow.txt", media_type="text/plain", content_base64="Zm9sbG93")
        ],
    )
    if clarification_id:
        body["clarification_id"] = clarification_id
    return append_task_message(
        app, str(task), body, idempotency_key=key, verified_host_grant=verified()
    )


def task_counts(task):
    with psycopg.connect(DSN) as c:
        sessions = [
            row[0]
            for row in c.execute(
                (
                    "SELECT session_id FROM execution_segments WHERE deployment_names"
                    "pace=%s AND task_id=%s"
                ),
                (NAMESPACE, task),
            )
        ]
        return (
            len(sessions),
            c.execute(
                (
                    "SELECT count(*) FROM session_events WHERE deployment_namespace=%"
                    "s AND session_id=ANY(%s)"
                ),
                (NAMESPACE, sessions),
            ).fetchone()[0],
            c.execute(
                (
                    "SELECT count(*) FROM artifact_payload_metadata WHERE deployment_"
                    "namespace=%s AND session_id=ANY(%s)"
                ),
                (NAMESPACE, sessions),
            ).fetchone()[0],
            c.execute(
                (
                    "SELECT count(*) FROM handoff_dispatch_outbox WHERE deployment_na"
                    "mespace=%s AND child_session_id=ANY(%s)"
                ),
                (NAMESPACE, sessions),
            ).fetchone()[0],
        )


# Active follow-up and completed lost-ACK replay: exactly one event/file/receipt.
task, original = seed()
response = send(task, "active")
assert response.status_code == 201, response.body
assert response.body["active_segment_id"] == str(task)
before = task_counts(task)
puts = objects.puts
replay = send(task, "active")
assert replay.body == response.body and task_counts(task) == before and objects.puts == puts
changed = send(task, "active", content="different")
assert changed.status_code == 409 and task_counts(task) == before
waiting, prior = seed("waiting")
answer = send(waiting, "clar", content="yes", clarification_id="qa-clar")
assert answer.status_code == 201 and answer.body["clarification_resolved"]
events = stores.events.list_for_session(SessionId(waiting))
recovered = recover_task(
    events,
    workspace=stores.workspaces.get_workspace(SessionId(waiting)),
    fallback_title="QA",
    attachment_reader=stores.artifact_payload_reader,
)
assert recovered.user_input == "original input" and recovered.attachments[0].text == "follow"

# Session adapter resolves native root ownership and reaches the same transaction.
session_task, _ = seed()
session_reply = ZebraAgentApi.append_session_message(
    app,
    str(session_task),
    dict(
        content="session input",
        attachments=[dict(file_name="s.txt", media_type="text/plain", content_base64="cw==")],
    ),
    verified_host_grant=verified(),
    idempotency_key="session-input",
)
assert session_reply.status_code == 201


def finish_turn(task):
    current = stores.tasks.get_task(task).active_segment_id
    events = stores.events.list_for_session(current)
    turn = current_turn(events)
    event = SessionEvent.create(
        session_id=current,
        sequence=events[-1].sequence + 1,
        event_type=EventType.TURN_COMPLETED,
        actor=EventActor.HARNESS,
        payload=dict(turn_id=turn.turn_id, turn_index=turn.turn_index, closes_segment=False),
    )
    stores.events.append(event)
    events.append(event)
    stores.sessions.save_session(rebuild_session(events))
    stores.workspaces.save_workspace(rebuild_workspace(events))
    return tuple(events)


image_input = dict(
    file_name="pixel.png",
    media_type="image/png",
    content_base64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jD1cAAAAASUVORK5CYII=",
)


def raw_input(task, key, **options):
    return append_task_message(
        app,
        str(task),
        dict(content="image follow up", attachments=[image_input], **options),
        idempotency_key=key,
        verified_host_grant=verified(),
    )


def assert_options(task, profile="deepseek-v4-flash-executor-v1", effort="high"):
    current = stores.tasks.get_task(task).active_segment_id
    events = stores.events.list_for_session(current)
    recovered = recover_task(
        events,
        workspace=stores.workspaces.get_workspace(current),
        fallback_title="QA",
        attachment_reader=stores.artifact_payload_reader,
    )
    assert recovered.model_invocation_policy.profile_id == profile
    assert recovered.model_invocation_policy.reasoning_effort.value == effort
    return events


# Resolve each option independently from the latest native input, then persist it
# into each new event: Worker recovery must agree with image admission.
switched, _ = seed(profile="deepseek-v4-pro-executor-v1")
first = send(switched, "switch-profile")
assert first.status_code == 201, first.body
finish_turn(switched)
omitted = raw_input(switched, "inherit-latest")
assert omitted.status_code == 201, omitted.body
assert_options(switched)
for key, options in [
    ("terminal-inherit", {}),
    ("terminal-profile-only", {"model_profile": "deepseek-v4-flash-executor-v1"}),
]:
    target, _ = seed("terminal")
    reply = raw_input(target, key, **options)
    assert reply.status_code == 201, reply.body
    assert reply.body["rolled_over"]
    assert_options(target)

# Failure after child+input+metadata preparation but before outbox insertion is a
# total rollback; another connection sees no child/input/outbox before commit.
terminal, source_events = seed("terminal")
source_count = task_counts(terminal)
original_insert = handoff._insert_envelope_and_dispatch
observed = []
commit_errors = []
original_diagnostic_commit = PostgresSessionHandoffStore.commit


def diagnostic_commit(self, request):
    try:
        return original_diagnostic_commit(self, request)
    except Exception as error:
        chain = []
        while error is not None:
            chain.append(dict(type=type(error).__name__, message=str(error)[:1500]))
            error = error.__cause__
        commit_errors.append(chain)
        raise


def fail_before_dispatch(connection, namespace, operation, request):
    with psycopg.connect(DSN) as other:
        observed.append(
            other.execute(
                (
                    "SELECT count(*) FROM session_streams WHERE deployment_namespace="
                    "%s AND session_id=%s"
                ),
                (NAMESPACE, operation.target_session_id),
            ).fetchone()[0]
        )
    raise ValueError("injected crash before outbox visibility")


handoff._insert_envelope_and_dispatch = fail_before_dispatch
PostgresSessionHandoffStore.commit = diagnostic_commit
try:
    failed = send(terminal, "rollback-terminal")
finally:
    handoff._insert_envelope_and_dispatch = original_insert
    PostgresSessionHandoffStore.commit = original_diagnostic_commit
assert failed.status_code == 409 and observed == [0] and task_counts(terminal) == source_count, (
    dict(
        status=failed.status_code,
        body=failed.body,
        commit_errors=commit_errors,
        observed=observed,
        before=source_count,
        after=task_counts(terminal),
    )
)
with psycopg.connect(DSN) as c:
    reserved = c.execute(
        (
            "SELECT target_session_id FROM handoff_operations WHERE deploymen"
            "t_namespace=%s AND source_session_id=%s AND status='preparing'"
        ),
        (NAMESPACE, terminal),
    ).fetchone()[0]
resumed = send(terminal, "rollback-terminal")
assert resumed.status_code == 201, resumed.body
assert resumed.body["active_segment_id"] == str(reserved) and resumed.body["rolled_over"]
child = SessionId(UUID(resumed.body["active_segment_id"]))
assert task_counts(terminal)[0] == 2 and task_counts(terminal)[3] == 1
assert stores.events.list_for_session(SessionId(terminal))[: len(source_events)] == list(
    source_events
)
child_events = stores.events.list_for_session(child)
assert (
    child_events[-1].payload["content"] == "follow up" and child_events[-1].payload["attachments"]
)
recovered = recover_task(
    child_events,
    workspace=stores.workspaces.get_workspace(child),
    fallback_title="QA",
    attachment_reader=stores.artifact_payload_reader,
)
assert recovered.user_input == "follow up" and recovered.attachments[0].text == "follow"

# A subsequent active-child append rebuilds the original root Task, never a
# second independent Task rooted at the already-attached child Segment.
child_prefix = finish_turn(terminal)
root_sequence = stores.tasks.get_task(terminal).current_sequence
child_reply = raw_input(terminal, "active-child-inherit")
assert child_reply.status_code == 201, child_reply.body
assert child_reply.body["task_id"] == str(terminal) and child_reply.body[
    "active_segment_id"
] == str(child)
assert child_reply.body["current_sequence"] > root_sequence, dict(
    body=child_reply.body,
    prior_root_sequence=root_sequence,
    canonical_root_sequence=stores.tasks.get_task(terminal).current_sequence,
)
assert child_reply.body["current_sequence"] == stores.tasks.get_task(terminal).current_sequence, (
    dict(
        body=child_reply.body,
        canonical_root_sequence=stores.tasks.get_task(terminal).current_sequence,
    )
)
assert task_counts(terminal)[0] == 2 and task_counts(terminal)[3] == 1
assert stores.events.list_for_session(child)[: len(child_prefix)] == list(child_prefix)
assert_options(terminal)
with psycopg.connect(DSN) as c:
    assert (
        c.execute(
            (
                "SELECT task_id FROM execution_segments WHERE deployment_namespac"
                "e=%s AND session_id=%s"
            ),
            (NAMESPACE, child),
        ).fetchone()[0]
        == terminal
    )
    coordinates = c.execute(
        (
            "SELECT task_id,task_sequence FROM session_events WHERE deploymen"
            "t_namespace=%s AND session_id=%s AND sequence=%s"
        ),
        (NAMESPACE, child, child_reply.body["active_segment_sequence"]),
    ).fetchone()
    assert coordinates == (terminal, child_reply.body["current_sequence"]), (
        coordinates,
        child_reply.body,
    )

# Actual commit with lost HTTP acknowledgement replays without another put or dispatch.
lost, _ = seed("terminal")
original_commit = PostgresSessionHandoffStore.commit


def lose_ack(self, request):
    original_commit(self, request)
    raise TimeoutError("injected acknowledgement loss after actual commit")


PostgresSessionHandoffStore.commit = lose_ack
try:
    try:
        send(lost, "lost-ack")
    except TimeoutError:
        pass
    else:
        raise AssertionError("Expected lost acknowledgement")
finally:
    PostgresSessionHandoffStore.commit = original_commit
before = task_counts(lost)
puts = objects.puts
assert send(lost, "lost-ack").status_code == 201
assert task_counts(lost) == before and objects.puts == puts and before[0] == 2 and before[3] == 1

# Distinct terminal follow-ups cannot both create an open human turn/dispatch.
concurrent, _ = seed("terminal")
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(lambda key: send(concurrent, key), ("winner-a", "winner-b")))
assert sorted(r.status_code for r in results) == [201, 409], [r.body for r in results]
assert task_counts(concurrent)[0] == 2 and task_counts(concurrent)[3] == 1
same, _ = seed("terminal")
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(lambda _: send(same, "same-key"), range(2)))
assert all(r.status_code == 201 for r in results) and results[0].body == results[1].body
assert task_counts(same)[0] == 2 and task_counts(same)[3] == 1
print(
    "PASS real PostgreSQL active/session/clarification input, exact r"
    "eplay, atomic rollover rollback/recovery, lost ACK, concurrent t"
    "erminal admission and unchanged original events"
)
