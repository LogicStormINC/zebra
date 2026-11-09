"""Run: python3 tests/test_history_checks.py; exercise finite native SSE recovery."""

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "history", Path(__file__).resolve().parents[1] / "zebra_erpnext/history.py"
)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


class Reply:
    closed = False

    def iter_lines(self, **kwargs):
        events = [
            dict(
                event_id="u",
                event_type="user_message_received",
                sequence=1,
                payload={"content": "查询"},
            ),
            dict(
                event_id="a",
                event_type="answer_committed",
                sequence=4,
                payload={"assistant_message": "人民币"},
            ),
        ]
        for item in events:
            yield ("data: " + json.dumps(item)).encode()
            yield b""
        yield b'data: {"type":"CUSTOM","name":"zebra.stream.recovery_complete","value":{}}'
        raise AssertionError("Snapshot tried to tail live events")

    def close(self):
        self.closed = True


r = Reply()
projected = h.messages(h.read_events(r, 10))
assert r.closed and [x["content"] for x in projected] == ["查询", "人民币"]
r = Reply()
assert len(h.read_events(r, 4)) == 2 and r.closed
print("PASS native SSE history finite-prefix recovery and message projection")


class LongReply(Reply):
    def iter_lines(self, **kwargs):
        yield b": keepalive"
        for n in range(2101):
            yield (
                "data: "
                + json.dumps(
                    dict(
                        sequence=n,
                        event_id=str(n),
                        event_type="answer_committed",
                        payload={"assistant_message": str(n)},
                    )
                )
            ).encode()
        yield b'data: {"type":"CUSTOM","name":"zebra.stream.recovery_complete"}'
        raise AssertionError("Kept tailing after recovery")


r = LongReply()
events = h.read_events(r, 2200)
assert len(events) == 2000 and h.messages(events)[-1]["content"] == "2100" and r.closed
print("PASS recent history survives 2000+ events and leading keepalive")

public_state = h.public_state
assert public_state({"status": "suspended"})["run_state"]["phase"] == "paused"
assert public_state({"status": "stopped"})["run_state"] == {
    "phase": "terminal",
    "outcome": "cancelled",
    "availableActions": [],
}
assert public_state({"status": "awaiting_approval"})["run_state"]["phase"] == "waiting_for_user"
assert (
    public_state({"status": "ready"}, pending_command=True)["run_state"]["phase"] == "reconciling"
)
events = [
    {
        "event_type": "CLARIFICATION_REQUESTED",
        "payload": {"clarification_id": "old", "question": "old secret", "context": "never expose"},
    },
    {
        "event_type": "CLARIFICATION_REQUESTED",
        "payload": {
            "clarification_id": "active",
            "question": "Which customer?",
            "choices": ["A", "B"],
            "context": "never expose",
        },
    },
]
value = public_state(
    {"status": "waiting_input", "clarification_context": {"clarification_id": "active"}}, events
)
assert value["clarification"] == {
    "clarification_id": "active",
    "question": "Which customer?",
    "choices": ["A", "B"],
}
assert (
    public_state(
        {"status": "completed", "clarification_context": {"clarification_id": "active"}}, events
    )["clarification"]
    is None
)
assert (
    public_state(
        {"status": "waiting_input", "clarification_context": {"clarification_id": "missing"}},
        events,
    )["clarification"]
    is None
)
print("PASS public paused/stopped/approval/unknown submission and active clarification projection")
