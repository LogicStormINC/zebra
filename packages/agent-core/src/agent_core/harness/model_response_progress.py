"""Observe public model speech and draft-verification progress, not private reasoning."""

from typing import TYPE_CHECKING

from agent_core.harness.models import HarnessEventDraft

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
