"""Actual continuation dispatch -> native loop -> fake provider request capture."""

import overlay_imports as overlay_imports

# isort: split
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace as SimpleNamespace
from uuid import UUID, uuid4

import test_initial_http_input as f
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.image_attachments import ImageAttachmentContextInput
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.models import HarnessAttempt, HarnessContext, HarnessTask
from agent_core.harness.orchestrator import SingleAttemptOrchestrator
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.continuation_dispatch import run_continuation

now = f.NOW
original = AttachmentContextInput(
    attachment_id=uuid4(), file_name="original.txt", media_type="text/plain", text="ORIGINAL FILE"
)
new = AttachmentContextInput(
    attachment_id=uuid4(),
    file_name="new.txt",
    media_type="text/plain",
    text="NEW CLARIFICATION TEXT",
)
old = AttachmentContextInput(
    attachment_id=uuid4(),
    file_name="previous.txt",
    media_type="text/plain",
    text="PREVIOUS RESPONSE FILE",
)
image = ImageAttachmentContextInput(
    attachment_id=uuid4(),
    file_name="new.png",
    media_type="image/png",
    payload=b"bounded image",
    width=1,
    height=1,
    sha256=sha256(b"bounded image").hexdigest(),
)
call = ToolCall(
    tool_call_id=new_tool_call_id(),
    name="agent.clarify",
    arguments={"question": "Which?"},
    created_at=now,
    provider_call_id="clar-call",
)
conversation = (
    SessionMessage(
        message_id=new_message_id(), role=MessageRole.USER, content="ORIGINAL FILE", created_at=now
    ),
    SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.ASSISTANT,
        content="Which?",
        tool_calls=(call,),
        created_at=now,
    ),
)
pending = ClarificationContinuation(
    tool_call=call,
    response="yes",
    conversation=conversation,
    model_calls_used=1,
    tool_calls_executed=0,
    assistant_message="Which?",
    attachment_ids=(str(new.attachment_id), str(image.attachment_id)),
)
context = HarnessContext(
    task=HarnessTask(
        title="QA",
        user_input="original task",
        attachments=(original, old, new),
        image_attachments=(image,),
        max_model_calls=3,
    ),
    session=f.bootstrap.session,
    attempt=HarnessAttempt(number=2, started_at=now),
)
for rebase in (False, True):
    current = pending
    if rebase:
        assistant = conversation[-1].model_copy(
            update={"metadata": {"provider_reasoning_required": True}}
        )
        current = replace(pending, conversation=(*conversation[:-1], assistant))
    gateway = ScriptedModelGateway(
        (
            ScriptedModelResponse(
                ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Done.",
                        created_at=now,
                    )
                )
            ),
        )
    )
    orchestrator = SingleAttemptOrchestrator(gateway, object(), object())
    result = run_continuation(orchestrator, context, continuation=None, clarification=current)
    assert len(gateway.requests) == 1
    messages = gateway.requests[0]
    joined = "\n".join(m.content for m in messages)
    assert "ORIGINAL FILE" in joined and "NEW CLARIFICATION TEXT" in joined
    assert "PREVIOUS RESPONSE FILE" not in joined
    assert sum("NEW CLARIFICATION TEXT" in m.content for m in messages) == 1
    assert messages[-1].role is MessageRole.USER and messages[-1].provider_image_data_urls == (
        "data:image/png;base64,Ym91bmRlZCBpbWFnZQ==",
    )
    assert result.metadata["model_calls_used"] == 2 and result.metadata["tool_calls_executed"] == 0
    if not rebase:
        assert messages[-2].role is MessageRole.TOOL and messages[:2] == conversation
print(
    "PASS real clarification dispatch normal/rebased provider request"
    ": original file retained, new text+image once, previous files ab"
    "sent, counters/tool pairing preserved"
)

# Real durable boundary: native stop-result serializer excludes provider image
# URLs, then canonical refs recover original + prior clarification images.

rebuild_session = __import__(
    "agent_core.application.session_projection", fromlist=("rebuild_session",)
).rebuild_session
rebuild_workspace = __import__(
    "agent_core.application.workspace_projection", fromlist=("rebuild_workspace",)
).rebuild_workspace
EventActor = __import__("agent_core.domain.events", fromlist=("EventActor",)).EventActor
EventType = __import__("agent_core.domain.events", fromlist=("EventType",)).EventType
SessionEvent = __import__("agent_core.domain.events", fromlist=("SessionEvent",)).SessionEvent
ImageAttachmentInput = __import__(
    "agent_core.domain.image_attachments", fromlist=("ImageAttachmentInput",)
).ImageAttachmentInput
clarification_stop_result = __import__(
    "agent_core.harness.clarification_step", fromlist=("clarification_stop_result",)
).clarification_stop_result
clarification_tool_result = __import__(
    "agent_core.harness.clarification_step", fromlist=("clarification_tool_result",)
).clarification_tool_result
image_data_urls = __import__(
    "agent_core.harness.image_messages", fromlist=("image_data_urls",)
).image_data_urls
tool_result_message = __import__(
    "agent_core.harness.model_step_support", fromlist=("tool_result_message",)
).tool_result_message
recover_clarification_continuation = __import__(
    "zebra_agent_worker.clarification_continuation",
    fromlist=("recover_clarification_continuation",),
).recover_clarification_continuation
recover_task = __import__(
    "zebra_agent_worker.task_recovery", fromlist=("recover_task",)
).recover_task

objects = f.Objects()
sid = f.bootstrap.session.session_id
events = list(f.bootstrap.events)
first_input = next(event for event in events if event.event_type is EventType.USER_MESSAGE_RECEIVED)
original_image = ImageAttachmentInput(
    file_name="original.png", media_type="image/png", payload=b"original image", width=1, height=1
)
original_event, _ = f.prepare_http_input(
    objects, "erpnext", f.authority, first_input, (original_image,)
)
# An earlier human turn's image must never leak into this turn's recovery.
earlier_image = ImageAttachmentInput(
    file_name="earlier.png", media_type="image/png", payload=b"earlier image", width=1, height=1
)
earlier_event, _ = f.prepare_http_input(
    objects, "erpnext", f.authority, first_input, (earlier_image,)
)
events = [earlier_event if event.event_id == first_input.event_id else event for event in events]
SessionMessageAppendCommand = __import__(
    "agent_core.application", fromlist=("SessionMessageAppendCommand",)
).SessionMessageAppendCommand
SessionMessageAppendService = __import__(
    "agent_core.application", fromlist=("SessionMessageAppendService",)
).SessionMessageAppendService
current_turn = __import__("agent_core.application", fromlist=("current_turn",)).current_turn

events.append(
    SessionEvent.create(
        session_id=sid,
        sequence=len(events),
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    )
)
turn = current_turn(events)
events.append(
    SessionEvent.create(
        session_id=sid,
        sequence=len(events),
        event_type=EventType.TURN_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"turn_id": turn.turn_id, "turn_index": 0, "closes_segment": False},
    )
)
current_input = SessionMessageAppendService().build_event(
    session=rebuild_session(events),
    next_sequence=len(events),
    command=SessionMessageAppendCommand(content="Current original input", prior_human_turns=1),
)
original_event, _ = f.prepare_http_input(
    objects, "erpnext", f.authority, current_input, (original_image,)
)
events.append(original_event)
events.append(
    SessionEvent.create(
        session_id=sid,
        sequence=len(events),
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    )
)
original_url = "data:image/png;base64,b3JpZ2luYWwgaW1hZ2U="
prior_url = "data:image/png;base64,cHJpb3IgaW1hZ2U="
original_message = SessionMessage(
    message_id=new_message_id(),
    role=MessageRole.USER,
    content="Original question",
    created_at=now,
    provider_image_data_urls=(original_url,),
)
prior_call = ToolCall(
    tool_call_id=new_tool_call_id(),
    name="agent.clarify",
    arguments={"question": "First?"},
    created_at=now,
    provider_call_id="first",
)


def request(call, messages):
    emitted = []
    clarification_stop_result(
        context,
        messages=list(messages),
        completion=ModelCompletion(assistant_message=messages[-1]),
        tool_call=call,
        emitted_events=emitted,
        model_calls_used=1,
        tool_calls_executed=0,
        metadata={},
    )
    draft = emitted[-1]
    assert "data:image" not in str(draft.payload) and "provider_image_data_urls" not in str(
        draft.payload
    )
    event = SessionEvent.create(
        session_id=sid,
        sequence=len(events),
        event_type=draft.event_type,
        actor=draft.actor,
        payload=draft.payload,
    )
    events.append(event)


def response(call, attachment):
    draft = SessionEvent.create(
        session_id=sid,
        sequence=len(events),
        event_type=EventType.CLARIFICATION_RESPONDED,
        actor=EventActor.USER,
        payload={
            "content": "Answer",
            "clarification_id": str(call.tool_call_id),
            "selected_choice": False,
        },
    )
    event, _ = f.prepare_http_input(objects, "erpnext", f.authority, draft, (attachment,))
    events.append(event)


prior_assistant = SessionMessage(
    message_id=new_message_id(),
    role=MessageRole.ASSISTANT,
    content="First?",
    created_at=now,
    tool_calls=(prior_call,),
)
request(prior_call, (original_message, prior_assistant))
response(
    prior_call,
    ImageAttachmentInput(
        file_name="prior.png", media_type="image/png", payload=b"prior image", width=1, height=1
    ),
)
prior_tool = tool_result_message(
    prior_call,
    clarification_tool_result(prior_call.tool_call_id, str(prior_call.tool_call_id), "Answer"),
    created_at=now,
)
prior_image_message = SessionMessage(
    message_id=new_message_id(),
    role=MessageRole.USER,
    content="Previous clarification image",
    created_at=now,
    provider_image_data_urls=(prior_url,),
)
events.append(
    SessionEvent.create(
        session_id=sid,
        sequence=len(events),
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 2},
    )
)
current_call = ToolCall(
    tool_call_id=new_tool_call_id(),
    name="agent.clarify",
    arguments={"question": "Second?"},
    created_at=now,
    provider_call_id="second",
)
current_assistant = SessionMessage(
    message_id=new_message_id(),
    role=MessageRole.ASSISTANT,
    content="Second?",
    created_at=now,
    tool_calls=(current_call,),
)
request(
    current_call,
    (original_message, prior_assistant, prior_tool, prior_image_message, current_assistant),
)
response(
    current_call,
    f.TextAttachmentInput(
        file_name="current.txt", media_type="text/plain", payload=b"CURRENT TEXT DELTA"
    ),
)


class Reader:
    def read_payload_bytes(self, session_id, uri):
        return objects.payloads[UUID(uri.removeprefix("artifact://"))]


recovered = recover_task(
    events, workspace=rebuild_workspace(events), fallback_title="QA", attachment_reader=Reader()
)
assert len(recovered.image_attachments) == 2 and len(recovered.attachments) == 1
assert "earlier.png" not in {item.file_name for item in recovered.image_attachments}
pending = recover_clarification_continuation(events)
assert pending is not None and not any(
    message.provider_image_data_urls for message in pending.conversation
)
restored_context = HarnessContext(
    task=HarnessTask(
        title="QA",
        user_input=recovered.user_input,
        attachments=recovered.attachments,
        image_attachments=recovered.image_attachments,
        max_model_calls=3,
    ),
    session=rebuild_session(events),
    attempt=HarnessAttempt(number=2, started_at=now),
)


class RequestCaptured(RuntimeError):
    pass


class CaptureGateway:
    def __init__(self):
        self.requests = []

    def complete(self, messages, *, tools=()):
        self.requests.append(tuple(messages))
        raise RequestCaptured()


for pending_conversation in (
    pending.conversation,
    tuple(
        message.model_copy(update={"provider_image_data_urls": (original_url, prior_url)})
        if index == 0
        else message
        for index, message in enumerate(pending.conversation)
    ),
):
    current = replace(pending, conversation=pending_conversation)
    gateway = CaptureGateway()
    try:
        run_continuation(
            SingleAttemptOrchestrator(gateway, object(), object()),
            restored_context,
            continuation=None,
            clarification=current,
        )
    except RequestCaptured:
        pass
    else:
        raise AssertionError("Expected provider request")
    messages = gateway.requests[0]
    urls = tuple(url for message in messages for url in message.provider_image_data_urls)
    assert urls.count(original_url) == 1 and urls.count(prior_url) == 1
    assert sum("CURRENT TEXT DELTA" in message.content for message in messages) == 1
print(
    "PASS native clarification event serialization -> recovery -> act"
    "ual dispatch restores original/prior images exactly once, new te"
    "xt delta only, no durable data URLs"
)
