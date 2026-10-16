"""Observe public model speech and draft-verification progress, not private reasoning."""

from dataclasses import asdict, replace
from typing import TYPE_CHECKING

from agent_core.domain.events import EventType
from agent_core.harness.model_commentary import plan_response
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output_lifecycle import public_output_lock
from agent_core.ports.worker_progress import WorkerProgressTimeout

if TYPE_CHECKING:
    from agent_core.harness.public_output import ProgressiveEventSink


def observe_model_response(progress: "ProgressiveEventSink", event: HarnessEventDraft) -> None:
    payload = event.payload
    progress._commentary.publish(payload)
    text = payload.get("assistant_message")
    progress._model_spoke |= (
        isinstance(text, str)
        and bool(text.strip())
        and text != "Tool calls proposed."
        and payload.get("response_stage") != "public_expression"
    )
    progress._stop_wait(f"model:{payload.get('model_call_id', '')}")
    if payload.get("response_stage") == "candidate" and progress._started:
        progress.publish(
            f"checking:{payload.get('model_call_id', '')}",
            "status",
            "verification",
            progress._text(
                "正在核对已取得的证据与答案要求；当前内容尚未最终确认。",
                "Checking collected evidence and answer requirements; this draft is not final.",
            ),
        )


def dispatch_public_event(progress: "ProgressiveEventSink", event: HarnessEventDraft) -> None:
    deferred = False
    try:
        with public_output_lock(
            progress._lock,
            progress._emission_scope,
            progress._closing if progress._emission_scope else None,
        ):
            if progress._timer_error is not None:
                raise progress._timer_error
            if event.event_type is EventType.MODEL_REQUEST_STARTED:
                event = replace(
                    event,
                    payload={**event.payload, "public_output_policy": asdict(progress.policy)},
                )
            if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
                event = replace(
                    event, payload=plan_response(event.payload, progress._commentary.reserved)
                )
            committed = False
            try:
                progress._sink(event)
                committed = True
                if not progress._closed:
                    progress._observe(event)
                    if event.event_type is EventType.MODEL_REQUEST_STARTED:
                        progress._publish_pending()
            except WorkerProgressTimeout as error:
                if not (committed or error.canonical_committed):
                    raise
                deferred = True
                # ponytail: only derived display state may lag; next sink reconciles
                # canonical identities before another append, with fresh authority.
                if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
                    progress._commentary.defer(event.payload)
                    progress._active.discard(f"model:{event.payload.get('model_call_id', '')}")
                    progress._cancel_timer()
                elif event.event_type is EventType.ANSWER_COMMITTED:
                    progress._closed = True
                raise
    except WorkerProgressTimeout:
        if not deferred:
            raise
