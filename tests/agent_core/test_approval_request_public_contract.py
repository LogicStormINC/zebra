"""Wave 4.5 contract: raw approval_requested carries a public approval_id.

The public SSE proxy (FinOS Phase 1) needs a live approval identity before any
terminal GET. The projection derives approval_id from the segment id; this
fixture pins the raw event to the same value so sanitizers can pass it through.
"""

from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessModelStep, HarnessTask, SingleAttemptOrchestrator

NOW = datetime(2026, 8, 13, 6, 31, 12, tzinfo=UTC)

TOOLS = (
    ModelToolDefinition(
        name="command.run",
        description="Run a command.",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
    ),
)


class ApprovalOnCommandPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.REQUIRE_APPROVAL,
            reason="approval required",
            policy_profile="test",
        )


class NoopGateway:
    def execute(self, tool_call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="{}",
        )


def _completion(content: str, tool_call: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=(tool_call,),
    )


def _approval_fixture() -> dict[str, object]:
    """Raw public SSE line shape produced by serialize_task_event (Zebra)."""
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": "ls"},
        created_at=NOW,
        provider_call_id="provider-approval",
    )
    result = HarnessLoop().run(
        HarnessTask(title="Approval contract", user_input="Run the command."),
        SingleAttemptOrchestrator(
            ScriptedModelGateway(
                responses=(
                    ScriptedModelResponse(
                        completion=_completion("Run it.", tool_call),
                    ),
                )
            ),
            ApprovalOnCommandPolicy(),
            NoopGateway(),
            model_step=HarnessModelStep(available_tools=TOOLS),
        ).run,
        created_at=NOW,
    )
    approval_events = [
        event
        for event in result.events
        if event.event_type is EventType.APPROVAL_REQUESTED
    ]
    assert len(approval_events) == 1
    event = approval_events[0]
    payload = event.payload

    # Contract: the raw event exposes a live approval identity equal to the
    # segment/session id that decide_agent_approval accepts and that the
    # public projection exposes as approval data.approval_id.
    assert payload["approval_id"] == str(event.session_id)

    return {
        "event_id": str(event.event_id),
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "actor": event.actor.value,
        "created_at": event.created_at.isoformat(),
        "payload": dict(payload),
    }


def test_approval_requested_carries_public_approval_id() -> None:
    raw = _approval_fixture()
    payload = raw["payload"]

    # Raw stream truth: identity fields plus the fields the FinOS sanitizer
    # must keep dropping (raw arguments, policy internals, model context).
    for field in (
        "approval_id",
        "tool_name",
        "tool_call_id",
        "reason",
        "arguments",
        "policy_profile",
        "assistant_message",
        "call_fingerprint",
    ):
        assert field in payload, field
    assert payload["tool_name"] == "command.run"
    assert isinstance(payload["approval_id"], str) and payload["approval_id"]
    assert isinstance(payload["tool_call_id"], str) and payload["tool_call_id"]


def test_finos_public_sse_envelope_fixture() -> None:
    raw = _approval_fixture()

    # FinOS Phase 1 sanitized envelope: schema_version, identity, and the
    # per-type allowlist only (approval_id, tool_name, reason, tool_call_id).
    envelope = {
        "schema_version": "finos.zebra-public-event.v1",
        "event_id": raw["event_id"],
        "sequence": raw["sequence"],
        "event_type": raw["event_type"],
        "created_at": raw["created_at"],
        "payload": {
            field: raw["payload"][field]
            for field in ("approval_id", "tool_name", "reason", "tool_call_id")
        },
    }

    assert envelope["event_type"] == "approval_requested"
    assert envelope["sequence"] == raw["sequence"]
    assert envelope["created_at"].endswith("+00:00")
    assert set(envelope["payload"]) == {
        "approval_id",
        "tool_name",
        "reason",
        "tool_call_id",
    }
    assert envelope["payload"]["approval_id"] == raw["payload"]["approval_id"]
    for hidden in ("arguments", "policy_profile", "assistant_message", "call_fingerprint"):
        assert hidden not in envelope["payload"]
