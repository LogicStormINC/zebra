import json

from zebra_agent_api.stream_v2_reader import canonical_wire, parse_record, stream_notice


def test_large_escaped_replacement_frames_are_bounded_and_deterministic():
    content = '你好🙂"\\\n' * 9000
    event = {"type": "TEXT_MESSAGE_CONTENT", "messageId": "message:call", "delta": content}
    record = "id: canonical\ndata: " + json.dumps(event) + "\n\n"
    frames = list(canonical_wire(record, event))
    assert len(frames) > 10
    assert all(len(frame.encode()) <= 16384 for _, frame in frames)
    assert [index for index, _ in frames[:-1]] == list(range(len(frames) - 1))
    assert frames[-1][0] is None
    assert "".join(parse_record(frame)[1]["value"]["content"] for _, frame in frames) == content
    assert frames == list(canonical_wire(record, event))


def test_canonical_commit_follows_complete_replacement_and_preserves_assessment():
    event = {
        "type": "CUSTOM",
        "name": "zebra.answer_committed",
        "value": {
            "model_call_id": "call",
            "assistant_message": "final" * 10000,
            "delivery_assessment": {"status": "complete"},
        },
    }
    frames = list(canonical_wire(stream_notice(event["name"], event["value"]), event))
    last = parse_record(frames[-1][1])[1]
    assert last["name"] == "zebra.answer_committed"
    assert last["value"]["replacement_committed"] is True
    assert last["value"]["delivery_assessment"] == {"status": "complete"}
    # A clear starts a new replacement even when accepted text shares the raw
    # model response's first chunks. The exact authoritative body follows it.
    clear = parse_record(frames[0][1])[1]
    assert clear["name"] == "zebra.message_replace"
    assert clear["value"]["content"] == "" and clear["value"]["last"] is True
    assert parse_record(frames[1][1])[1]["value"]["chunk_index"] == 0
    assert all(len(frame.encode()) <= 16384 for _, frame in frames)
    assert (
        "".join(parse_record(frame)[1]["value"]["content"] for _, frame in frames[:-1])
        == "final" * 10000
    )


def test_large_tool_frame_keeps_all_canonical_data():
    event = {"type": "TOOL_CALL_ARGS", "toolCallId": "tool", "delta": "x" * 90000}
    frames = list(canonical_wire("data: " + json.dumps(event) + "\n\n", event))
    restored = json.loads(
        "".join(parse_record(frame)[1]["value"]["content"] for _, frame in frames)
    )
    assert restored == event
    assert all(len(frame.encode()) <= 16384 for _, frame in frames)


def test_large_assessment_is_chunked_without_widening_existing_checkpoint_budget():
    event = {
        "type": "CUSTOM",
        "name": "zebra.answer_committed",
        "value": {
            "model_call_id": "call",
            "assistant_message": "final",
            "delivery_assessment": {"evidence_refs": ["https://fixture.test/" + "a" * 200] * 150},
        },
    }
    frames = list(canonical_wire(stream_notice(event["name"], event["value"]), event))
    assert all(len(frame.encode()) <= 12280 for _, frame in frames)
    chunks = [
        parse_record(frame)[1]["value"]["content"]
        for _, frame in frames
        if parse_record(frame)[1]["name"] == "zebra.canonical_chunk"
    ]
    commit = json.loads("".join(chunks))
    assert commit["value"]["delivery_assessment"] == event["value"]["delivery_assessment"]


def test_raw_prior_committed_facts_receipts_and_private_expression_keep_correct_boundaries():
    events = [
        {
            "event_id": "old-fact",
            "sequence": 2,
            "event_type": "answer_committed",
            "payload": {"model_call_id": "old", "assistant_message": "prior committed answer"},
        },
        {
            "event_id": "receipt",
            "sequence": 3,
            "event_type": "client_effect_receipt_recorded",
            "payload": {"effect_id": "finished"},
        },
        {
            "event_id": "expression",
            "sequence": 4,
            "event_type": "model_response_received",
            "payload": {
                "model_call_id": "private",
                "response_stage": "public_expression",
                "assistant_message": "private candidate",
            },
        },
        {
            "event_id": "legacy-delta",
            "sequence": 5,
            "event_type": "model_response_delta",
            "payload": {"model_call_id": "old", "content_delta": "legacy delta"},
        },
        {
            "event_id": "placeholder",
            "sequence": 6,
            "event_type": "model_response_received",
            "payload": {"model_call_id": "tool", "assistant_message": "Tool calls proposed."},
        },
    ]
    output = []
    for event in events:
        output.append(
            [
                parse_record(frame)[1]
                for _, frame in canonical_wire(
                    "id: " + str(event["sequence"]) + "\ndata: " + json.dumps(event) + "\n\n", event
                )
            ]
        )
    assert output[0][0] == events[0]
    assert output[0][-1]["name"] == "zebra.answer_committed"
    assert output[0][-1]["value"]["model_call_id"] == "old"
    assert output[1] == [events[1]]
    assert output[2] == [
        events[2]
    ]  # Existing canonical fact/privacy flow; no temporary replacement.
    assert output[3] == [events[3]]  # Legacy deltas never become replacement-per-delta.
    assert output[4][-1]["value"]["content"] == ""


def test_maximal_signed_cursor_and_unicode_draft_chunk_fit_final_wire():
    from zebra_agent_api.stream_v2_cursor import StreamV2Cursor, StreamV2CursorCodec
    from zebra_agent_api.stream_v2_reader import StreamV2Reader
    from zebra_agent_api.stream_v2_wire import draft_wire

    from tests.agent_core.test_transient_output_contract import frame, generation

    identity = generation()
    content = "🙂" * 1000
    core = frame(identity, content_delta=content)
    cursor = StreamV2Cursor("s" * 128, "d" * 2048, identity.generation_id, "123-0", 0)
    reader = object.__new__(StreamV2Reader)
    reader.codec = StreamV2CursorCodec(b"s" * 32)
    pieces = list(draft_wire(core))
    assert (
        "".join(parse_record(piece)[1]["value"]["content_delta"] for _, piece in pieces) == content
    )
    assert all(
        parse_record(piece)[1]["value"]["task_id"] == str(core.task_id)
        and parse_record(piece)[1]["value"]["run_id"] == core.run_id
        for _, piece in pieces
    )
    assert all(len(reader._signed(piece, cursor).encode()) <= 16384 for _, piece in pieces)


def test_valid_raw_unicode_source_does_not_expand_canonical_assembly_budget():
    event = {
        "event_type": "tool_call_completed",
        "sequence": 10,
        "event_id": "fact",
        "payload": {"output": "🙂" * 200000},
    }
    record = "data: " + json.dumps(event) + "\n\n"
    assert len(record.encode()) > 2_000_000
    assert len(json.dumps(event, ensure_ascii=False).encode()) < 1_048_576
    frames = list(canonical_wire(record, event))
    normalized = "".join(parse_record(frame)[1]["value"]["content"] for _, frame in frames)
    assert len(normalized.encode()) < 1_048_576
    assert json.loads(normalized) == event
    assert all(len(frame.encode()) <= 12280 for _, frame in frames)


def test_historical_commits_without_call_keep_distinct_stable_canonical_identities():
    from agent_integrations.ag_ui import AgUiCursor

    identities = []
    for event_id in ("first", "second"):
        payload = {"assistant_message": "historical answer", "model_call_id": None}
        raw = {"event_id": event_id, "event_type": "answer_committed", "payload": payload}
        custom = {"type": "CUSTOM", "name": "zebra.answer_committed", "value": payload}
        cursor = AgUiCursor(thread_id="thread", run_id="run", sequence=1, event_id=event_id)
        outputs = []
        for event, source_id in ((raw, "1"), (custom, cursor.encode())):
            record = "id: " + source_id + "\ndata: " + json.dumps(event) + "\n\n"
            first = list(canonical_wire(record, event))
            assert first == list(canonical_wire(record, event))
            outputs.append(parse_record(first[-1][1])[1]["value"]["message_id"])
        assert outputs == [f"message:event:{event_id}"] * 2
        identities.append(outputs[0])
    assert len(set(identities)) == 2


def test_actual_tail_retains_bounded_closure_state_across_5000_historical_responses(monkeypatch):
    import asyncio
    from datetime import UTC, datetime, timedelta
    from time import monotonic
    from types import SimpleNamespace

    from agent_core.ports.transient_output import TransientOutputBatch
    from agent_integrations.redis_transient_discovery import TransientDescriptor
    from zebra_agent_api.stream_v2_cursor import StreamV2CursorCodec
    from zebra_agent_api.stream_v2_reader import StreamV2Reader

    from tests.agent_core.test_transient_output_contract import authorization, frame, generation

    async def scenario(active):
        auth = authorization(generation())
        descriptor = TransientDescriptor(
            scope=auth.scope, fence=auth.lease_fence, request_sequence=1
        )
        finished = False
        late_reads = []

        class Notifications:
            def key(self, *args, **kwargs):
                return str(args)

            async def barrier(self, key):
                return "0-0"

            async def wait(self, positions, **kwargs):
                await asyncio.sleep(0.001)
                return positions

        def read_after(**kwargs):
            if finished:
                late_reads.append(True)
            return TransientOutputBatch(
                frames=(frame(auth.scope.generation),) if finished else (),
                next_cursor=kwargs["cursor"],
            )

        reader = object.__new__(StreamV2Reader)
        reader.notifications = Notifications()
        reader.port = SimpleNamespace(_client=object())
        reader.codec = StreamV2CursorCodec(b"s" * 32)
        reader.authority = SimpleNamespace(
            qualify=lambda *args: datetime.now(UTC) + timedelta(seconds=20)
        )
        reader._read_port = lambda *args: SimpleNamespace(read_after=read_after)
        monkeypatch.setattr(
            "zebra_agent_api.stream_v2_reader.discover",
            lambda *args: (descriptor, "revision") if active else None,
        )
        bound = SimpleNamespace(
            host=SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=20)),
            authority=SimpleNamespace(allowed_session_ids=("segment",)),
            namespace="owned",
            task_id="task",
            lane="exact-server-lane",
        )
        context = reader.context(bound, kind="task", token=None, full_recovery=True)

        async def source():
            nonlocal finished
            for index in range(5000):
                event = {
                    "event_type": "model_response_received",
                    "payload": {"model_call_id": f"historical-{index}"},
                }
                yield "id: " + str(index) + "\ndata: " + json.dumps(event) + "\n\n"
            finished = True
            yield (
                "data: "
                + json.dumps(
                    {
                        "event_type": "model_response_received",
                        "payload": {"model_call_id": auth.scope.generation.model_call_id},
                    }
                )
                + "\n\n"
            )
            yield stream_notice("zebra.stream.recovery_complete", {})
            await asyncio.sleep(0.03)

        stream = reader.tail(
            context,
            source(),
            deadline=monotonic() + 10,
            disconnected=lambda: asyncio.sleep(0, result=False),
        )
        facts = 0
        async for wire in stream:
            event = parse_record(wire)[1]
            if event.get("event_type"):
                facts += 1
            # Inspect the real suspended connection, excluding caller/source-owned history.
            state = stream.ag_frame.f_locals
            assert sum(len(value) for value in state.values() if isinstance(value, set)) <= 1
            if finished:
                assert event.get("name") != "zebra.stream.draft"
        assert facts == 5001
        assert not late_reads

    asyncio.run(scenario(False))
    asyncio.run(scenario(True))
