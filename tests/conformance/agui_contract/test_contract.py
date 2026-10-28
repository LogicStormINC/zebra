"""Run with unittest discovery so imports never resolve an unrelated tests package."""

import json
import tempfile
import unittest
from pathlib import Path
from shutil import copyfile

from agent_integrations.ag_ui import AgUiCursor, AgUiProjectionError, AgUiProjector
from legacy_baseline import CODEC, IDENTITY, baseline, legacy_records, scenarios
from selfcheck import ROOT, check, event_catalog
from zebra_agent_api.stream_v2_wire import canonical_wire, parse_record


class FrozenContractTests(unittest.TestCase):
    def test_frozen_schema_and_normative_union(self) -> None:
        check()

    def test_integrity_rejects_byte_drift_and_catalog_omissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("upstream.json", "schema-1.0.json", "event-catalog.json"):
                copyfile(ROOT / name, root / name)
            with (root / "schema-1.0.json").open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(AssertionError, "frozen schema bytes changed"):
                check(root)
            copyfile(ROOT / "schema-1.0.json", root / "schema-1.0.json")
            catalog = json.loads((root / "event-catalog.json").read_text())
            (root / "event-catalog.json").write_text(json.dumps(catalog[:-1]))
            with self.assertRaisesRegex(AssertionError, "catalog drift"):
                check(root)

    def test_catalog_ignores_unreferenced_enum_and_rejects_duplicate_union(self) -> None:
        schema = json.loads((ROOT / "schema-1.0.json").read_bytes())
        original = event_catalog(schema)
        schema["$defs"]["Unrelated"] = {"enum": ["IMAGINARY_EVENT"]}
        self.assertEqual(event_catalog(schema), original)
        schema["$defs"]["Event"]["oneOf"].append(schema["$defs"]["Event"]["oneOf"][0])
        with self.assertRaisesRegex(AssertionError, "duplicate event tags"):
            event_catalog(schema)

    def test_current_python_projector_encoder_v2_and_cursor_golden(self) -> None:
        frozen = json.loads((ROOT / "fixtures" / "legacy-0.1.19.json").read_text())
        self.assertEqual(baseline(), frozen)
        tags = {
            parse_record(record)[1]["type"]
            for case in frozen["scenarios"].values()
            for record in case["sse"]
        }
        self.assertEqual(
            tags,
            {
                "RUN_STARTED",
                "RUN_FINISHED",
                "RUN_ERROR",
                "TEXT_MESSAGE_START",
                "TEXT_MESSAGE_CONTENT",
                "TEXT_MESSAGE_END",
                "TOOL_CALL_START",
                "TOOL_CALL_ARGS",
                "TOOL_CALL_END",
                "TOOL_CALL_RESULT",
                "STATE_SNAPSHOT",
                "STATE_DELTA",
                "MESSAGES_SNAPSHOT",
                "CUSTOM",
            },
        )

    def test_replay_matches_every_exact_frame_suffix(self) -> None:
        for name, events in scenarios().items():
            records = legacy_records(events)
            for index, (cursor, _) in enumerate(records):
                with self.subTest(case=name, index=index):
                    tail = AgUiProjector().project(events, IDENTITY, after=cursor.encode())
                    encoded = [
                        event.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for event in tail.events
                    ]
                    self.assertEqual(
                        encoded, [parse_record(record)[1] for _, record in records[index + 1 :]]
                    )
                    invalid = cursor.model_copy(update={"event_id": "wrong-event"})
                    with self.assertRaises(AgUiProjectionError):
                        AgUiProjector().project(events, IDENTITY, after=invalid)
                    foreign = cursor.model_copy(update={"run_id": "foreign-run"})
                    with self.assertRaises(AgUiProjectionError):
                        AgUiProjector().project(events, IDENTITY, after=foreign)
            for event in events:
                cursor = AgUiCursor(
                    thread_id=IDENTITY.thread_id,
                    run_id=IDENTITY.run_id,
                    sequence=event.sequence,
                    event_id=str(event.event_id),
                )
                tail = AgUiProjector().project(events, IDENTITY, after=cursor.encode())
                self.assertEqual(
                    [
                        e.model_dump(mode="json", by_alias=True, exclude_none=True)
                        for e in tail.events
                    ],
                    [
                        parse_record(record)[1]
                        for position, record in records
                        if position.sequence > event.sequence
                    ],
                )

    def test_legacy_tool_end_is_delayed_until_result_and_v2_replaces_text(self) -> None:
        records = legacy_records(scenarios()["text_tool_plan"])
        tagged = [(cursor, parse_record(record)[1]) for cursor, record in records]
        self.assertEqual(
            [event["type"] for cursor, event in tagged if cursor.sequence == 4],
            ["TOOL_CALL_START", "TOOL_CALL_ARGS"],
        )
        self.assertEqual(
            [event["type"] for cursor, event in tagged if cursor.sequence == 5],
            ["TOOL_CALL_END", "TOOL_CALL_RESULT"],
        )
        for _, record in records:
            event = parse_record(record)[1]
            if event["type"] == "TEXT_MESSAGE_CONTENT":
                expanded = list(canonical_wire(record, event))
                self.assertEqual(parse_record(expanded[0][1])[1]["name"], "zebra.message_replace")
        frozen = baseline()
        for case in frozen["scenarios"].values():
            for item in case["v2"]:
                cursor = CODEC.decode(item["cursor"], scope="g0-scope")
                self.assertEqual(CODEC.encode(cursor), item["cursor"])
                with self.assertRaises(ValueError):
                    CODEC.decode(item["cursor"], scope="other-scope")

    def test_large_v2_chunk_expansion_is_bounded_and_ordered(self) -> None:
        event = {
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": "message:large",
            "delta": "证据😀" * 5000,
        }
        record = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        frames = list(canonical_wire(record, event))
        self.assertGreater(len(frames), 1)
        self.assertEqual([index for index, _ in frames], list(range(len(frames) - 1)) + [None])
        values = [parse_record(wire)[1]["value"] for _, wire in frames]
        self.assertEqual("".join(value["content"] for value in values), event["delta"])
        self.assertTrue(all(len(wire.encode()) <= 12280 for _, wire in frames))
        self.assertEqual([value["chunk_index"] for value in values], list(range(len(frames))))
        self.assertEqual([value["last"] for value in values], [False] * (len(frames) - 1) + [True])


if __name__ == "__main__":
    unittest.main()
