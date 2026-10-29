"""Invocation attribution from canonical parent delegation and exact settled epochs."""

from hashlib import sha256

from ag_ui.core import Event, SubagentErrorEvent, SubagentFinishedEvent, SubagentStartedEvent
from agent_core.domain.events import EventActor, EventType, SessionEvent

from agent_integrations.ag_ui.activity_projection import activity
from agent_integrations.ag_ui.payload_validation import required_payload_text
from agent_integrations.ag_ui.standard_state import StandardProjectionState


def subagent_events(
    event: SessionEvent,
    state: StandardProjectionState,
    task_id: str,
) -> tuple[Event, ...]:
    timestamp = int(event.created_at.timestamp() * 1000)
    if event.event_type in {
        EventType.SESSION_RESUMED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_FAILED,
        EventType.SESSION_CANCELLED,
    }:
        state.child_epoch_cut = True
    if event.event_type is EventType.SUBAGENT_DELEGATED and event.actor is EventActor.HARNESS:
        state.subagent_usage_unknown = True
        if state.child_epoch_cut:
            state.children.clear()
            state.child_epoch_cut = False
        child = required_payload_text(event.payload, "child_task_id")
        call = required_payload_text(event.payload, "tool_call_id")
        name = required_payload_text(event.payload, "tool_name")
        invocation = "delegation:" + str(event.event_id)
        if child in state.children and state.children[child]["invocation"] == invocation:
            return ()
        state.children[child] = {
            "invocation": invocation,
            "call": call,
            "name": name,
            "sequence": str(event.sequence),
            "session": str(event.session_id),
        }
        return (
            activity(
                invocation,
                "subagent",
                {
                    "invocation_id": invocation,
                    "tool_call_id": call,
                    "name": name,
                    "status": "delegated",
                },
                timestamp,
            ),
        )
    if event.event_type in {
        EventType.SUBAGENT_STARTED,
        EventType.SUBAGENT_COMPLETED,
        EventType.SUBAGENT_FAILED,
        EventType.SUBAGENT_CANCELLED,
    }:
        if event.actor is EventActor.HARNESS:
            state.subagent_usage_unknown = True
        payload = event.payload
        research_call, research_name, research_invocation = (
            payload.get(k) for k in ("tool_call_id", "tool_name", "subagent_id")
        )
        if (
            event.actor is not EventActor.HARNESS
            or research_name != "agent.research"
            or not isinstance(research_call, str)
            or not research_call.strip()
            or not isinstance(research_invocation, str)
            or not research_invocation.strip()
        ):
            return ()
        key = "research:" + research_call + ":" + research_invocation
        metadata = {"zebra": {"timing": "observed_after_execution", "version": 1}}
        if event.event_type is EventType.SUBAGENT_STARTED:
            if key in state.children:
                return ()
            state.children[key] = {"invocation": key, "call": research_call, "name": research_name}
            return ()
        if key not in state.children:
            return ()
        state.children.pop(key)
        start = SubagentStartedEvent(
            subagent_run_id=key,
            name=research_name,
            parent_tool_call_id=research_call,
            metadata=metadata,
        )
        if event.event_type is EventType.SUBAGENT_COMPLETED:
            return (start, SubagentFinishedEvent(subagent_run_id=key, metadata=metadata))
        return (
            start,
            SubagentErrorEvent(
                subagent_run_id=key,
                metadata=metadata,
                message="Research execution ended without success",
                code=event.event_type.value,
            ),
        )
    if (
        event.event_type is not EventType.SESSION_COMMAND_ACCEPTED
        or event.actor is not EventActor.HARNESS
        or event.payload.get("kind") != "resume"
        or not state.children
    ):
        return ()
    delegated = {child: row for child, row in state.children.items() if "sequence" in row}
    if not delegated:
        return ()
    command = event.payload.get("payload")
    results = command.get("child_results") if isinstance(command, dict) else None
    if not isinstance(results, list) or len(results) != len(delegated):
        return ()
    statuses: dict[str, str] = {}
    for result in results:
        if not isinstance(result, dict):
            return ()
        result_child, result_status = result.get("child_task_id"), result.get("status")
        if (
            not isinstance(result_child, str)
            or result_child not in state.children
            or result_child in statuses
            or result_status not in {"completed", "failed", "cancelled"}
        ):
            return ()
        statuses[result_child] = str(result_status)
    digest = sha256(":".join(sorted(statuses)).encode()).hexdigest()
    expected = max(int(child["sequence"]) for child in delegated.values())
    if (
        event.payload.get("idempotency_key") != f"child-wakeup:{task_id}:{digest}"
        or type(event.payload.get("expected_revision")) is not int
        or event.payload["expected_revision"] != expected
        or any(child["session"] != str(event.session_id) for child in delegated.values())
    ):
        return ()
    # This exact HARNESS fact is emitted transactionally by ChildWakeupProcessor
    # from terminal links and durable child events. Do not re-read mutable children
    # during historical projection, or expose their private summary/conversation.
    frames: list[Event] = []
    for child, status in statuses.items():
        invocation = state.children[child]["invocation"]
        frames.append(
            SubagentStartedEvent(
                subagent_run_id=invocation,
                name=state.children[child]["name"],
                parent_tool_call_id=state.children[child]["call"],
                metadata={"zebra": {"timing": "observed_completion", "version": 1}},
            )
        )
        if status == "completed":
            frames.append(SubagentFinishedEvent(timestamp=timestamp, subagent_run_id=invocation))
        else:
            frames.append(
                SubagentErrorEvent(
                    timestamp=timestamp,
                    subagent_run_id=invocation,
                    message="Delegated execution " + status,
                    code="zebra_child_" + status,
                )
            )
    for child in statuses:
        state.children.pop(child)
    return tuple(frames)
