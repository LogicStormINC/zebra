"""Reconcile owned page/canonical records; no model, network or database access."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def decompose(root: Path, label: str) -> dict[str, object]:
    canonical = json.loads((root / f"canonical-{label}.safe.json").read_text())
    page = json.loads((root / f"page-{label}.private.json").read_text())
    assert canonical["status"] == "completed" and canonical["mode"] == "transient_v2"
    frames = page["frames"]
    sent = next(frame["wall_ms"] for frame in frames if frame["kind"] == "sent")

    def normalize(text: str) -> str:
        return "".join(text.split())

    prefix = normalize(page["finalText"])[:16]
    assert len(prefix) == 16
    first = next(
        frame["ms"]
        for frame in frames
        if frame["kind"] == "body" and prefix in normalize(frame["text"])
    )
    events = canonical["events"]
    starts = [event for event in events if event["type"] == "model_request_started"]
    responses = [event for event in events if event["type"] == "model_response_received"]
    assert len(starts) == len(responses) and len(starts) >= 1
    assert all(
        event["thinking"] == "enabled" and event["effort"] == "high" and event["retry"] == 0
        for event in responses
    )
    assert all(
        start["model_call_id"] == response["model_call_id"]
        for start, response in zip(starts, responses, strict=True)
    )
    assert responses[-1]["response_stage"] == "candidate"
    # ponytail: disjoint envelopes include receipt overhead; they are not pure wire time.
    intervals = [
        (start["wall_ms"], response["wall_ms"])
        for start, response in zip(starts[:-1], responses[:-1], strict=True)
    ]
    intervals.append((starts[-1]["wall_ms"], sent + first))
    categories = {
        "startup": starts[0]["wall_ms"] - sent,
        "model_before_candidate": sum(end - start for start, end in intervals[:-1]),
        "candidate_to_visible_prefix": intervals[-1][1] - intervals[-1][0],
    }
    tool_counts = {}
    for tool in ("web.search", "web.fetch"):
        tool_starts = [
            event
            for event in events
            if event["type"] == "tool_execution_started" and event["tool"] == tool
        ]
        tool_ends = [
            event
            for event in events
            if event["type"] == "tool_execution_completed" and event["tool"] == tool
        ]
        assert {event["tool_call_id"] for event in tool_starts} == {
            event["tool_call_id"] for event in tool_ends
        }
        tool_counts[tool] = len(tool_starts)
        # Merge overlaps; independently chosen extra rounds remain counted as real work.
        spans = sorted(
            (
                start["wall_ms"],
                next(
                    end["wall_ms"]
                    for end in tool_ends
                    if end["tool_call_id"] == start["tool_call_id"]
                ),
            )
            for start in tool_starts
        )
        merged: list[tuple[float, float]] = []
        for start, end in spans:
            assert start <= end
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        categories[tool] = sum(end - start for start, end in merged)
        intervals.extend(merged)
    ordered = sorted(intervals)
    assert all(
        end <= start + 0.1 for (_, end), (start, _) in zip(ordered, ordered[1:], strict=False)
    )
    assert all(end >= start for start, end in ordered)
    categories["handoffs"] = first - sum(categories.values())
    assert all(value >= -0.1 for value in categories.values())
    assert abs(sum(categories.values()) - first) < 0.1
    assert not any(event["type"] == "tool_execution_failed" for event in events)
    return dict(
        label=label,
        run=canonical["run"],
        first_body_ms=first,
        whole_ms=canonical["completed_ms"] - sent,
        categories_ms=categories,
        models=len(starts),
        tools=tool_counts,
    )


if __name__ == "__main__":
    print(json.dumps([decompose(Path(sys.argv[1]), label) for label in sys.argv[2:]], indent=2))
