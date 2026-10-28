"""Actual v2 encoder fixtures for the paired Host's real-HTTP decoder acceptance."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from agent_integrations.ag_ui.contracts import AgUiCursor
from zebra_agent_api.stream_v2_cursor import StreamV2Cursor, StreamV2CursorCodec
from zebra_agent_api.stream_v2_reader import StreamV2Reader
from zebra_agent_api.stream_v2_wire import canonical_wire


def test_actual_encoder_long_cursor_large_tool_and_final(tmp_path, record_property):
    task, run = str(uuid4()), str(uuid4())
    answer = "最终正文🙂\n" * 60000
    output = json.dumps({"output": "工具证据\n" * 18000}, ensure_ascii=False)
    events = [
        {"type": "RUN_STARTED", "threadId": task, "runId": run},
        {"type": "TOOL_CALL_START", "toolCallId": "tool-one", "toolCallName": "web.fetch"},
        {
            "type": "TOOL_CALL_ARGS",
            "toolCallId": "tool-one",
            "delta": json.dumps({"url": "https://example.test"}),
        },
        {"type": "TOOL_CALL_END", "toolCallId": "tool-one"},
        {
            "type": "TOOL_CALL_RESULT",
            "toolCallId": "tool-one",
            "messageId": "result-one",
            "content": output,
            "role": "tool",
        },
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "message:final-call", "delta": answer},
        {
            "type": "CUSTOM",
            "name": "zebra.answer_committed",
            "value": {
                "model_call_id": "final-call",
                "assistant_message": answer,
                "delivery_assessment": {"status": "complete"},
            },
        },
        {"type": "RUN_FINISHED", "threadId": task, "runId": run, "outcome": {"type": "success"}},
    ]
    reader = object.__new__(StreamV2Reader)
    reader.codec = StreamV2CursorCodec(b"disposable-protocol-fixture-key-32")
    frames = []
    for index, event in enumerate(events):
        source = AgUiCursor(
            thread_id=task, run_id=run, sequence=index, event_id=str(uuid4()), frame_index=0
        )
        cursor = StreamV2Cursor(
            "a" * 64,
            durable=source.encode(),
            generation="generation-" + "a" * 64,
            live_id="1234567890000-1",
            live_offset=7,
        )
        record = (
            "id: " + source.encode() + "\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        )
        for ordinal, wire in canonical_wire(record, event):
            signed = reader._signed(wire, replace(cursor, chunk_index=ordinal))
            token = signed.splitlines()[0].removeprefix("id: ")
            assert 512 < len(token) <= 4096
            assert reader.codec.decode(token, scope="a" * 64).durable == source.encode()
            assert len(signed.encode()) <= 16384
            frames.append({"token": token, "wire": signed})
    assert len(frames) > 50 and len({f["token"] for f in frames}) == len(frames)
    result = {
        "task_id": task,
        "run_id": run,
        "frames": frames,
        "answer": answer,
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
    }
    dest = Path(os.environ.get("ZEBRA_LONG_WIRE_OUTPUT", tmp_path / "wire.json"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False))
    record_property("wire_frames", len(frames))
    record_property("max_cursor", max(len(f["token"]) for f in frames))
    record_property("answer_bytes", len(answer.encode()))
