"""Deterministic bounded v2 wire expansion; durable checkpoint semantics stay v1."""

import json
from collections.abc import Iterator

from agent_core.domain.transient_output import TransientTextFrame
from agent_integrations.ag_ui import AgUiCursor


def stream_notice(name: str, value: dict[str, object]) -> str:
    return (
        "data: "
        + json.dumps({"type": "CUSTOM", "name": name, "value": value}, separators=(",", ":"))
        + "\n\n"
    )


def parse_record(record: str) -> tuple[str | None, dict[str, object]]:
    source_id = None
    data = []
    for line in record.splitlines():
        if line.startswith("id:"):
            source_id = line[3:].strip()
        if line.startswith("data:"):
            data.append(line[5:].strip())
    event = json.loads("\n".join(data)) if data else {}
    if not isinstance(event, dict):
        raise ValueError("canonical SSE record must be an object")
    return source_id, event


def canonical_call(event: dict[str, object]) -> str | None:
    if event.get("type") == "TEXT_MESSAGE_CONTENT":
        identity = event.get("messageId")
        return identity.removeprefix("message:") if isinstance(identity, str) else None
    if event.get("name") == "zebra.model_response" and isinstance(event.get("value"), dict):
        metadata = event["value"]
        assert isinstance(metadata, dict)
        value = metadata.get("model_call_id")
        return value if isinstance(value, str) else None
    payload = event.get("payload")
    if event.get("event_type") == "model_response_received" and isinstance(payload, dict):
        value = payload.get("model_call_id")
        return value if isinstance(value, str) else None
    return None


def _chunks(name: str, metadata: dict[str, object], content: str, *, key: str) -> Iterator[str]:
    index = 0
    while content or index == 0:
        lo, hi, accepted = 0, min(len(content), 12_280), None
        while lo <= hi:
            mid = (lo + hi) // 2
            wire = stream_notice(
                name,
                {**metadata, key: content[:mid], "chunk_index": index, "last": mid == len(content)},
            )
            if len(wire.encode()) <= 12_280:
                accepted, lo = (wire, mid), mid + 1
            else:
                hi = mid - 1
        if accepted is None or (accepted[1] == 0 and content):
            raise ValueError("canonical frame identities exceed their budget")
        yield accepted[0]
        content = content[accepted[1] :]
        index += 1
        if not content:
            break


def _canonical_record(record: str, event: dict[str, object]) -> Iterator[str]:
    if len(record.encode()) > 12_280:
        yield from _chunks(
            "zebra.canonical_chunk",
            {},
            json.dumps(event, separators=(",", ":"), ensure_ascii=False),
            key="content",
        )
    else:
        yield record


def _commit(value: dict[str, object], event_id: object) -> Iterator[str]:
    call = value.get("model_call_id")
    if not isinstance(call, str) and not isinstance(event_id, str):
        raise ValueError("committed answer requires canonical event identity")
    identity = f"message:{call}" if isinstance(call, str) else f"message:event:{event_id}"
    # ponytail: one bounded clear prevents legacy prefix deduplication from losing
    # a changed suffix's replacement start; no consumer or canonical body rewrite.
    yield from _chunks(
        "zebra.message_replace",
        {"message_id": identity, "model_call_id": call},
        "", key="content",
    )
    yield from _chunks(
        "zebra.message_replace",
        {
            "message_id": identity,
            "model_call_id": call,
        },
        str(value.get("assistant_message", "")),
        key="content",
    )
    notice = stream_notice(
        "zebra.answer_committed",
        {
            "message_id": identity,
            "model_call_id": call,
            "replacement_committed": True,
            "delivery_assessment": value.get("delivery_assessment", {}),
        },
    )
    yield from _canonical_record(notice, parse_record(notice)[1])


def canonical_wire(record: str, event: dict[str, object]) -> Iterator[tuple[int | None, str]]:
    def expand() -> Iterator[str]:
        if event.get("type") == "TEXT_MESSAGE_CONTENT" and isinstance(event.get("delta"), str):
            yield from _chunks(
                "zebra.message_replace",
                {
                    "message_id": event.get("messageId"),
                    "model_call_id": canonical_call(event),
                },
                str(event["delta"]),
                key="content",
            )
        elif event.get("name") == "zebra.answer_committed" and isinstance(event.get("value"), dict):
            value = event["value"]
            assert isinstance(value, dict)
            identity = event.get("event_id")
            if not isinstance(value.get("model_call_id"), str):
                source_id, _ = parse_record(record)
                if source_id:
                    identity = AgUiCursor.decode(source_id).event_id
            yield from _commit(value, identity)
        elif event.get("event_type") in {"model_response_received", "answer_committed"}:
            yield from _canonical_record(record, event)  # Raw transports retain the exact fact.
            payload = event.get("payload")
            if isinstance(payload, dict) and event.get("event_type") == "answer_committed":
                yield from _commit(payload, event.get("event_id"))
            elif isinstance(payload, dict) and payload.get("response_stage") != "public_expression":
                call = payload.get("model_call_id")
                content = payload.get("assistant_message")
                if isinstance(call, str) and isinstance(content, str):
                    yield from _chunks(
                        "zebra.message_replace",
                        {
                            "message_id": f"message:{call}",
                            "model_call_id": call,
                        },
                        "" if content == "Tool calls proposed." else content,
                        key="content",
                    )
        else:
            yield from _canonical_record(record, event)

    frames = expand()
    previous = next(frames, None)
    index = 0
    while previous is not None:
        following = next(frames, None)
        yield (index if following is not None else None), previous
        previous, index = following, index + 1


def draft_wire(frame: TransientTextFrame) -> Iterator[tuple[int | None, str]]:
    frames = _chunks(
        "zebra.stream.draft",
        {
            "task_id": str(frame.task_id),
            "run_id": frame.run_id,
            "message_id": frame.message_id,
            "generation_id": frame.generation_id,
            "offset": frame.offset,
        },
        frame.content_delta,
        key="content_delta",
    )
    previous = next(frames, None)
    index = 0
    while previous is not None:
        following = next(frames, None)
        yield (index if following is not None else None), previous
        previous, index = following, index + 1
