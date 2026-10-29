"""Explicit revision-two producer for native browser-effect and decision facts."""

import json
from collections.abc import Iterator, Sequence
from hashlib import sha256
from uuid import UUID

from ag_ui.core import (
    Event,
    RunErrorEvent,
    RunFinishedCancelledOutcome,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedSuccessOutcome,
    StateDeltaEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallResultEvent,
)
from agent_core.contracts.public_output import PublicOutputPayload
from agent_core.domain.events import EventActor, EventType, SessionEvent

from agent_integrations.ag_ui.activity_projection import activity
from agent_integrations.ag_ui.client_effect_projection import project_client_effect
from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.projection_state import ProjectionState
from agent_integrations.ag_ui.standard_interaction_binding import (
    bind_native_message,
    native_clarification_result,
    native_expired_effect,
)
from agent_integrations.ag_ui.standard_interaction_state import InteractionProjectionState
from agent_integrations.ag_ui.standard_interrupts import execution_patch, native_response_interrupt
from agent_integrations.ag_ui.standard_projection import StandardAgUiProjector
from agent_integrations.ag_ui.standard_state import StandardProjectionState
from agent_integrations.ag_ui.standard_usage import terminal_usage
from agent_integrations.coverage_public_events import strict_coverage_events


class InteractionAgUiProjector(StandardAgUiProjector):
    def __init__(self, profile_id: str = "agui-standard-1.0") -> None:
        self._projection_version = profile_id + ":r2"

    def project_events(
        self,
        events: Sequence[SessionEvent],
        identity: AgUiRunIdentity,
        *,
        state: ProjectionState | None = None,
        strict_coverage: bool = False,
    ) -> Iterator[tuple[SessionEvent, tuple[Event, ...]]]:
        if state is None:
            state = InteractionProjectionState()
        if not isinstance(state, InteractionProjectionState):
            raise AgUiProjectionError("interaction profile requires revision-two state")
        self._validate_stream(tuple(events), identity)
        if state.protocol_run_id is None and events:
            # Direct projector consumers without the checkpoint binder still
            # need a restorable checkpoint: derive the public Run identity
            # from this identity plus the first event anchor. The distinct
            # digest domain keeps it from impersonating a canonical
            # materializer-derived id. The id is window-relative (anchor =
            # first event of this batch), so it is only a projection-time
            # identity, never a durable checkpoint link.
            first = events[0]
            state.begin(
                "agui:"
                + sha256(
                    "\0".join(
                        (
                            "zebra:agui:interaction-run:2",
                            str(identity.session_id),
                            str(identity.thread_id),
                            str(identity.run_id),
                            str(first.event_id),
                        )
                    ).encode()
                ).hexdigest(),
                str(first.event_id),
            )
        state.strict_coverage = (
            strict_coverage or state.strict_coverage or strict_coverage_events(events)
        )
        version = self._projection_version + (":coverage" if state.strict_coverage else "")
        for event in events:
            bind_native_message(event, identity, state, projection_version=version)
            if event.event_type is EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED:
                effect = state.pending_effects.get(str(event.payload.get("client_effect_id")))
                if effect is not None:
                    if (
                        event.actor is not EventActor.TOOL
                        or event.idempotency_key
                        != "client-effect-receipt:" + str(effect["effect_id"])
                        or str(UUID(str(event.payload.get("receipt_id"))))
                        != event.payload.get("receipt_id")
                    ):
                        raise AgUiProjectionError("accepted receipt is not a canonical native fact")
                    if effect["request_digest"] != event.payload.get("request_digest"):
                        raise AgUiProjectionError("native receipt does not match its effect")
                    if state.accepted_receipt or event.payload.get("status") not in {
                        "succeeded",
                        "failed",
                        "declined",
                        "unavailable",
                        "stale_ui_state",
                    }:
                        raise AgUiProjectionError("unsupported native receipt combination")
                    state.accepted_receipt = {
                        "effect_id": str(effect["effect_id"]),
                        "tool_call_id": str(effect["tool_call_id"]),
                        "action_name": str(effect["action_name"]),
                        "request_digest": str(effect["request_digest"]),
                        "status": str(event.payload["status"]),
                        "receipt_id": str(event.payload["receipt_id"]),
                        "event_id": str(event.event_id),
                        "sequence": str(event.sequence),
                    }
                    state.pending_effects.pop(str(event.payload["client_effect_id"]))
            for source, frames in super().project_events(
                (event,), identity, state=state, strict_coverage=strict_coverage
            ):
                # close_public_messages only closes typed ModelCommentaryChunk
                # groups. Their native contract proves these exact classifications;
                # repeat them because the official consumer merges metadata shallowly.
                yield (
                    source,
                    tuple(
                        frame.model_copy(
                            update={
                                "metadata": {
                                    **frame.metadata,
                                    "zebra": {
                                        **frame.metadata["zebra"],
                                        "version": 2,
                                        "kind": "commentary",
                                        "meaningful": False,
                                        "evidence_refs": [],
                                    },
                                }
                            }
                        )
                        if isinstance(frame, TextMessageEndEvent)
                        and frame.metadata
                        and isinstance(frame.metadata.get("zebra"), dict)
                        and frame.metadata["zebra"].get("reason") == "protocol_slice_ended"
                        else frame
                        for frame in frames
                    ),
                )

    def _public_event(self, event: SessionEvent, *, strict: bool) -> SessionEvent | None:
        if strict:
            return super()._public_event(event, strict=True)
        if event.event_type in {
            EventType.CLIENT_EFFECT_SCHEDULED,
            EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED,
            EventType.APPROVAL_REJECTED,
        }:
            # These branches only consume explicit whitelisted fields below. The
            # private native conversation never enters a public event or snapshot.
            return event
        return super()._public_event(event, strict=strict)

    def _initial_snapshot(self, state: StandardProjectionState) -> dict[str, object]:
        if not isinstance(state, InteractionProjectionState):
            raise AgUiProjectionError("interaction profile requires revision-two state")
        return {
            **super()._initial_snapshot(state),
            "zebra": {"clientEffects": dict(state.pending_effects)},
        }

    def _standard_event(
        self, event: SessionEvent, identity: AgUiRunIdentity, state: StandardProjectionState
    ) -> tuple[Event, ...]:
        if not isinstance(state, InteractionProjectionState):
            raise AgUiProjectionError("interaction profile requires revision-two state")
        timestamp = int(event.created_at.timestamp() * 1000)
        if event.event_type is EventType.PUBLIC_OUTPUT:
            publication = PublicOutputPayload.model_validate(event.payload)
            frames = super()._standard_event(event, identity, state)
            classification = {
                "version": 2,
                "kind": publication.kind,
                "meaningful": publication.meaningful,
                "evidence_refs": list(publication.evidence_refs),
                **(
                    {"evidence_basis": publication.evidence_basis}
                    if publication.evidence_basis
                    else {}
                ),
            }
            return tuple(
                frame.model_copy(
                    update={
                        "metadata": {
                            **(frame.metadata or {}),
                            "zebra": {
                                **((frame.metadata or {}).get("zebra") or {}),
                                **classification,
                            },
                        }
                    }
                )
                if isinstance(frame, TextMessageStartEvent)
                else frame
                for frame in frames
            )
        if event.event_type is EventType.CLIENT_EFFECT_SCHEDULED:
            projected = project_client_effect(event, timestamp=timestamp)
            call = event.payload.get("tool_call_id")
            if not projected or call not in state.pending_tools or state.pending_effects:
                raise AgUiProjectionError("native effect requires one actual unanswered proposal")
            effect = projected[0].model_dump(mode="json", by_alias=True)["delta"][0]["value"]
            effect["tool_call_id"] = call
            effect["result_message_id"] = "tool-result:" + str(call)
            if effect["action_name"] != state.pending_tools[call]:
                raise AgUiProjectionError("native effect does not match its tool proposal")
            state.pending_effects[str(effect["effect_id"])] = effect
            state.turn_finished = True
            emitted = StateDeltaEvent.model_validate(
                {
                    "timestamp": timestamp,
                    "delta": [
                        {
                            "op": "add",
                            "path": "/zebra/clientEffects/" + str(effect["effect_id"]),
                            "value": effect,
                        }
                    ],
                }
            )
            return (
                emitted,
                execution_patch(state, {"status": "waiting_client_effect"}, timestamp),
                RunFinishedEvent(
                    timestamp=timestamp,
                    thread_id=identity.thread_id,
                    run_id=str(state.protocol_run_id),
                    outcome=RunFinishedSuccessOutcome(),
                    usage=terminal_usage(state),
                ),
            )
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED:
            payload = event.payload.get("payload")
            context = payload.get("client_preparation") if isinstance(payload, dict) else None
            result = payload.get("client_effect_result") if isinstance(payload, dict) else None
            if isinstance(result, dict):
                expired = result.get("status") == "expired"
                accepted = (
                    native_expired_effect(event, state) if expired else state.accepted_receipt
                )
                call = result.get("tool_call_id")
                if (
                    not accepted
                    or not expired
                    and event.sequence != int(accepted["sequence"]) + 1
                    or event.actor is not EventActor.HARNESS
                    or not expired
                    and event.idempotency_key != "client-effect-resume:" + accepted["effect_id"]
                    or result.get("client_effect_id") != accepted["effect_id"]
                    or call != accepted["tool_call_id"]
                    or result.get("action_name") != accepted["action_name"]
                    or result.get("status") != accepted["status"]
                    or not expired
                    and isinstance(context, dict)
                    and context.get("operation_id") != accepted["receipt_id"]
                    or state.pending_tools.get(str(call)) != accepted["action_name"]
                    or not isinstance(result.get("result"), dict)
                ):
                    raise AgUiProjectionError("native continuation lacks its original receipt")
                state.pending_tools.pop(str(call))
                state.accepted_receipt.clear()
                return (
                    execution_patch(state, {"status": "resuming"}, timestamp),
                    activity(
                        "execution:" + str(call),
                        "tool_execution",
                        {
                            "tool_call_id": str(call),
                            "status": "completed" if result["status"] == "succeeded" else "failed",
                            "client_effect_status": result["status"],
                        },
                        timestamp,
                    ),
                    ToolCallResultEvent(
                        timestamp=timestamp,
                        message_id="tool-result:" + str(call),
                        tool_call_id=str(call),
                        role="tool",
                        content=json.dumps(
                            {"status": result["status"], "result": result["result"]},
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ),
                    ),
                )
        if event.event_type is EventType.CLARIFICATION_RESPONDED and state.pending_clarification:
            human_result = native_clarification_result(event, state)
            call = str(human_result.tool_call_id)
            state.pending_tools.pop(call, None)
            return (
                activity(
                    "execution:" + call,
                    "tool_execution",
                    {
                        "tool_call_id": call,
                        "status": "completed",
                        "clarification_response": True,
                    },
                    timestamp,
                ),
                ToolCallResultEvent(
                    timestamp=timestamp,
                    message_id="tool-result:" + call,
                    tool_call_id=call,
                    content=human_result.output,
                    role="tool",
                ),
            )
        if event.event_type in {EventType.APPROVAL_REQUESTED, EventType.CLARIFICATION_REQUESTED}:
            state.interrupt_ack_pending = True
            frames = super()._standard_event(event, identity, state)
            outgoing: list[Event] = []
            for frame in frames:
                if isinstance(frame, RunFinishedEvent) and isinstance(
                    frame.outcome, RunFinishedInterruptOutcome
                ):
                    interrupts = [
                        native_response_interrupt(i, event.payload)
                        for i in frame.outcome.interrupts
                    ]
                    state.open_interrupts = {i.id: i for i in interrupts}
                    frame = frame.model_copy(
                        update={
                            "outcome": frame.outcome.model_copy(update={"interrupts": interrupts})
                        }
                    )
                outgoing.append(frame)
            return tuple(outgoing)
        if event.event_type is EventType.SESSION_CANCELLED:
            state.turn_finished = True
            return (
                execution_patch(state, {"status": "cancelled"}, timestamp),
                RunFinishedEvent(
                    timestamp=timestamp,
                    thread_id=identity.thread_id,
                    run_id=str(state.protocol_run_id),
                    outcome=RunFinishedCancelledOutcome(),
                    usage=terminal_usage(state),
                ),
            )
        if event.event_type is EventType.APPROVAL_REJECTED:
            state.turn_finished = True
            return (
                execution_patch(state, {"status": "failed"}, timestamp),
                RunErrorEvent(
                    timestamp=timestamp,
                    message="Native approval was rejected",
                    code="zebra_approval_rejected",
                    usage=terminal_usage(state),
                ),
            )
        return super()._standard_event(event, identity, state)
