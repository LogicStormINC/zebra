"""Run with installed native workspace Python; no network/model/ERP writes."""

import overlay_imports as overlay_imports

# isort: split

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import test_initial_http_input as f
from agent_core.application import current_turn
from agent_core.application.session_attachments import attachment_refs_from_event
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId as SessionId
from agent_storage.postgres import http_input_messages as storage
from zebra_agent_api.http_input_attachments import HttpInputIntent, has_raw_input_attachments
from zebra_agent_api.session_payloads import parse_append_session_message_payload
from zebra_agent_worker.task_recovery import recover_task

bootstrap = f.bootstrap
sid = bootstrap.session.session_id
base = list(bootstrap.events)
turn = current_turn(base)
started = SessionEvent.create(
    session_id=sid,
    sequence=len(base),
    event_type=EventType.HARNESS_ATTEMPT_STARTED,
    actor=EventActor.HARNESS,
    payload={"attempt_number": 1},
)
closed = SessionEvent.create(
    session_id=sid,
    sequence=len(base) + 1,
    event_type=EventType.TURN_COMPLETED,
    actor=EventActor.HARNESS,
    payload={"turn_id": turn.turn_id, "turn_index": 0, "closes_segment": False},
)
events = base + [started, closed]
objects = f.Objects()


class Admission:
    def prepare(self, authority, binding, event, attachments):
        return f.prepare_http_input(objects, "erpnext", authority, event, attachments)


payload = dict(
    content="next input",
    model_profile="deepseek-v4-flash-executor-v1",
    reasoning_effort="high",
    attachments=[dict(file_name="follow.txt", media_type="text/plain", content_base64="Zm9sbG93")],
)
parsed = parse_append_session_message_payload(payload)
assert isinstance(parsed, dict)
intent = HttpInputIntent(
    Admission(), f.bound, f.authority, parsed, "http-input:test", "stable-key", "b" * 64
)
prepared = intent.prepare(sid, len(events), datetime.now(UTC))
retry = intent.prepare(sid, len(events), datetime.now(UTC))
assert prepared.event.event_id == retry.event.event_id
assert (
    prepared.attachments.entries[0].reference.attachment_id
    == retry.attachments.entries[0].reference.attachment_id
)
assert len(objects.payloads) == 1, "A pending retry reuses immutable object identity"


class Connection(f.Connection):
    def __init__(self):
        super().__init__()
        self.receipt = None

    def execute(self, sql, args=()):
        if sql.startswith("SET CONSTRAINTS session_events_allocate_task_position"):
            return f.Row(None)
        if "SELECT active_segment_id FROM agent_tasks" in sql:
            return f.Row(dict(active_segment_id=sid))
        if "UPDATE control_plane_idempotency_records" in sql:
            self.receipt = args[0].obj
            return SimpleNamespace(rowcount=1)
        return super().execute(sql, args)


saved = {}
seen = []
patches = {
    "_lock_task": lambda *args: None,
    "_read_task_binding": lambda *args: f.bound,
    "append_event_in_transaction": lambda conn, namespace, event: seen.append(event) or event,
    "save_session_in_transaction": lambda *args: None,
    "save_workspace_in_transaction": lambda *args: None,
    "rebuild_task_in_transaction": lambda *args: SimpleNamespace(current_sequence=len(events)),
}
for name, value in patches.items():
    saved[name] = getattr(storage, name)
    setattr(storage, name, value)
c = Connection()
try:
    result = storage.materialize_http_input(
        c,
        "erpnext",
        prepared,
        session=rebuild_session(events),
        workspace=rebuild_workspace(events),
        events=events,
    )
    assert result.response_body == c.receipt and len(c.inserts) == 1 and len(seen) == 1
    canonical = seen[-1]
    assert canonical.event_id == prepared.event.event_id and canonical.sequence == len(events)
    assert attachment_refs_from_event(canonical)[0].file_name == "follow.txt"

    class Reader:
        def read_payload_bytes(self, session_id, uri):
            return objects.payloads[UUID(uri.removeprefix("artifact://"))]

    recovered = recover_task(
        events + [canonical],
        workspace=rebuild_workspace(events + [canonical]),
        fallback_title="QA",
        attachment_reader=Reader(),
    )
    assert recovered.user_input == "next input" and recovered.attachments[0].text == "follow"
    waiting = SessionEvent.create(
        session_id=sid,
        sequence=len(base) + 1,
        event_type=EventType.CLARIFICATION_REQUESTED,
        actor=EventActor.HARNESS,
        payload=dict(
            clarification_id="clar",
            tool_call_id="call",
            question="Which?",
            assistant_message="Choose",
            choices=["yes", "no"],
            attempt_number=1,
            conversation=[],
            model_calls_used=1,
            tool_calls_executed=0,
        ),
    )
    clar_events = base + [started, waiting]
    clar_payload = dict(
        content="yes",
        clarification_id="clar",
        attachments=[
            dict(file_name="clar.txt", media_type="text/plain", content_base64="Y2xhcg==")
        ],
    )
    clar_parsed = parse_append_session_message_payload(
        clar_payload, allow_clarification_attachments=True
    )
    assert isinstance(clar_parsed, dict)
    clar_intent = replace(intent, parsed=clar_parsed, key="clar-key", digest="c" * 64)
    clar_prepared = clar_intent.prepare(sid, len(clar_events), datetime.now(UTC))
    clar_result = storage.materialize_http_input(
        c,
        "erpnext",
        clar_prepared,
        session=rebuild_session(clar_events),
        workspace=rebuild_workspace(clar_events),
        events=clar_events,
    )
    assert clar_result.response_body["clarification_resolved"] is True
    assert seen[-1].event_type is EventType.CLARIFICATION_RESPONDED
    assert attachment_refs_from_event(seen[-1])[0].file_name == "clar.txt"
    recovered = recover_task(
        clar_events + [seen[-1]],
        workspace=rebuild_workspace(clar_events + [seen[-1]]),
        fallback_title="QA",
        attachment_reader=Reader(),
    )
    assert recovered.user_input == "read files" and recovered.attachments[0].text == "clar"
    before = len(seen)
    c.registry["active"] = False
    f.rejects(
        lambda: storage.materialize_http_input(
            c,
            "erpnext",
            prepared,
            session=rebuild_session(events),
            workspace=rebuild_workspace(events),
            events=events,
        )
    )
    assert len(seen) == before
finally:
    for name, value in saved.items():
        setattr(storage, name, value)
for value in (
    {"attachments": []},
    {"input": {"messages": [{"role": "user", "attachments": []}]}},
    {"input": {"messages": [{"role": "user", "content": [{"type": "binary", "data": "secret"}]}]}},
):
    assert has_raw_input_attachments(value)
assert not has_raw_input_attachments(
    {"input": {"messages": [{"role": "user", "content": "plain text"}]}}
)
print(
    "PASS follow-up/clarification canonical refs and Worker recovery,"
    " stable staged identities, atomic receipt composition and raw-in"
    "put rejection"
)
validate_attachment_context_budget = __import__(
    "agent_core.application.session_attachments", fromlist=("validate_attachment_context_budget",)
).validate_attachment_context_budget

validate_attachment_context_budget([prepared.attachments.entries[0].reference])
f.rejects(
    lambda: validate_attachment_context_budget([prepared.attachments.entries[0].reference] * 5)
)
validate_attachment_sources = __import__(
    "agent_storage.task_read_summary_rows", fromlist=("validate_attachment_sources",)
).validate_attachment_sources

frontier = dict(
    source_task=sid,
    member_task=sid,
    source_position=5,
    task_sequence=5,
    session_id=sid,
    segment_id=sid,
    source_sequence=6,
    segment_sequence=6,
    event_type=EventType.CLARIFICATION_RESPONDED.value,
    event_position_source_ready=True,
    event_position_source_cursor=6,
)
validate_attachment_sources([frontier], sid, 5)
print("PASS clarification context budget and canonical attachment-page source validation")
AgUiCommandEnvelope = __import__(
    "zebra_agent_api.ag_ui_command", fromlist=("AgUiCommandEnvelope",)
).AgUiCommandEnvelope
_command_payload = __import__(
    "zebra_agent_api.ag_ui_command", fromlist=("_command_payload",)
)._command_payload
submit_session_command = __import__(
    "zebra_agent_api.command_submission", fromlist=("submit_session_command",)
).submit_session_command

raw = AgUiCommandEnvelope.model_validate(
    dict(
        action="run",
        threadId=str(sid),
        runId="run",
        expectedRevision=1,
        input=dict(messages=[dict(id="m", role="user", content="read", attachments=[])]),
    )
)
f.rejects(lambda: _command_payload(raw))
no_events = SimpleNamespace(sessions=SimpleNamespace(get_session=lambda key: object()))
rejected = submit_session_command(
    no_events,
    str(sid),
    dict(kind="message", expected_revision=1, payload=dict(content="read", attachments=[])),
    idempotency_key="raw-files",
)
assert rejected.status_code == 400
print(
    "PASS AGUI and queued-command adapters reject raw attachment inte"
    "nt before any event access/write"
)
