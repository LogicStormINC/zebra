"""Publish only durable public facts; never candidate model deltas/reservations."""

from ag_ui.core import (
    CustomEvent,
    Event,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from agent_core.contracts.answer_events import DeliveryAssessmentPayload
from agent_core.contracts.public_output import PublicOutputPayload
from agent_core.domain.events import EventType, SessionEvent

from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.standard_state import StandardProjectionState


def public_text(event: SessionEvent, state: StandardProjectionState) -> tuple[Event, ...]:
    payload = event.payload
    timestamp = int(event.created_at.timestamp() * 1000)
    extension: tuple[Event, ...] = ()
    chunk = None
    if event.event_type is EventType.PUBLIC_OUTPUT:
        publication = PublicOutputPayload.model_validate(payload)
        key, content = publication.output_id, publication.content
        chunk = publication.commentary_chunk
    elif event.event_type is EventType.ANSWER_COMMITTED:
        key = "answer:" + str(event.event_id)
        answer = payload.get("assistant_message")
        if not isinstance(answer, str) or not answer.strip():
            raise AgUiProjectionError("answer commit requires public text")
        content = answer
        # Delivery state is separate from Run interruption. No unfiltered assessment body.
        raw_assessment = payload.get("delivery_assessment")
        assessment = (
            DeliveryAssessmentPayload.model_validate(raw_assessment)
            if raw_assessment is not None
            else None
        )
        status = assessment.status if assessment is not None else None
        extension = (
            CustomEvent(
                timestamp=timestamp,
                name="zebra.answer_committed.v1",
                value={
                    "message_id": "message:" + key,
                    **(
                        {
                            "delivery_assessment": assessment.model_dump(
                                mode="json", exclude_none=True
                            )
                        }
                        if assessment is not None
                        else {}
                    ),
                    "delivery_status": status
                    if status in {"complete", "partial", "blocked"}
                    else None,
                },
            ),
        )
    else:
        return ()
    if key in state.publications:
        return ()
    state.publications.add(key)
    message = "message:" + key
    start, end = True, True
    start_metadata: dict[str, object] | None = None
    if chunk is not None:
        group = f"commentary:{publication.model_call_id}:{chunk.source_sha256}"
        if state.commentary_offsets.get(group, 0) != chunk.index:
            raise AgUiProjectionError("published commentary chunks are out of order")
        message = group + ":" + str(state.protocol_run_id)
        start_metadata = {
            "zebra": {"version": 1, "publicationId": group, "firstChunkIndex": chunk.index}
        }
        start = group not in state.commentary_open
        end = chunk.index + 1 == chunk.count
        state.commentary_offsets[group] = chunk.index + 1
        state.commentary_open[group] = message
        if end:
            state.commentary_offsets.pop(group)
            state.commentary_open.pop(group)
    return (
        *(
            (
                TextMessageStartEvent(
                    timestamp=timestamp,
                    message_id=message,
                    role="assistant",
                    metadata=start_metadata,
                ),
            )
            if start
            else ()
        ),
        TextMessageContentEvent(timestamp=timestamp, message_id=message, delta=content),
        *((TextMessageEndEvent(timestamp=timestamp, message_id=message),) if end else ()),
        *extension,
    )


def close_public_messages(state: StandardProjectionState, timestamp: int) -> tuple[Event, ...]:
    """The protocol slice ended; never pretend the missing publication chunks arrived."""
    result = tuple(
        TextMessageEndEvent(
            timestamp=timestamp,
            message_id=message,
            metadata={
                "zebra": {
                    "publicationComplete": False,
                    "committed": False,
                    "reason": "protocol_slice_ended",
                }
            },
        )
        for message in state.commentary_open.values()
    )
    state.commentary_open.clear()
    return result
