"""QA-only commit-visibility brackets and calibrated paint-ready intervals.

Start before the measured event, poll off the HTTP path, and join by canonical
identity. No created_at, database wall clock, schema repair, or producer mutation.
Clock drift is an explicit assumption, not an inferred clock synchronization fact.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID, uuid4

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_event_pages import read_task_event_page
from agent_storage.postgres.task_replay_headers import read_run_header
from isolation import joint_preflight
from joint_commit_coverage import CommentaryCoverage
from support import Config, task_binding

MAX_EVENTS = 256
MAX_BYTES = 1_048_576


def _number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("nonfinite_or_non_numeric_clock")
    return float(value)


def _now_ms() -> float:
    return time.monotonic() * 1000


@dataclass(frozen=True, slots=True)
class ClockSample:
    reference_clock_id: str
    remote_clock_id: str
    send_ms: float
    remote_ms: float
    return_ms: float
    precision_ms: float = 1


def calibrated_clock_interval(
    lower_ms: float,
    upper_ms: float,
    *,
    remote_clock_id: str,
    reference_clock_id: str,
    samples: Sequence[ClockSample],
    drift_ppm: float,
    max_uncertainty_ms: float = 20,
    max_span_ms: float = 120_000,
) -> tuple[float, float]:
    """RPC-bracketed affine-clock bounds, expanded by the declared drift ceiling.

    Bracket both endpoints with calibration samples; reject clock/reset/order
    inconsistencies. Never derive a midpoint or assume symmetric network delay.
    """
    lower, upper = _number(lower_ms), _number(upper_ms)
    drift, ceiling, span = map(_number, (drift_ppm, max_uncertainty_ms, max_span_ms))
    if lower > upper or not 0 <= drift <= 1000 or not 0 < ceiling <= 100:
        raise ValueError("invalid_clock_interval_or_budget")
    if not 0 < span <= 120_000 or not 2 <= len(samples) <= 32:
        raise ValueError("calibration_count_or_span")
    previous_return = previous_remote = -math.inf
    offsets: list[tuple[float, float, float]] = []
    for sample in samples:
        if (
            sample.reference_clock_id != reference_clock_id
            or sample.remote_clock_id != remote_clock_id
            or not reference_clock_id
            or not remote_clock_id
        ):
            raise ValueError("clock_identity_mismatch")
        sent, remote, returned, precision = map(
            _number, (sample.send_ms, sample.remote_ms, sample.return_ms, sample.precision_ms)
        )
        if (
            sent > returned
            or sent < previous_return
            or remote < previous_remote
            or not 0 <= precision <= 5
            or returned - sent + 2 * precision > ceiling
        ):
            raise ValueError("calibration_order_precision_or_uncertainty")
        offsets.append((sent - remote - precision, returned - remote + precision, remote))
        previous_return, previous_remote = returned, remote
    if (
        offsets[0][2] > lower
        or offsets[-1][2] < upper
        or samples[-1].return_ms - samples[0].send_ms > span
    ):
        raise ValueError("calibration_does_not_bracket_measurement")
    intervals = []
    for endpoint in (lower, upper):
        low = max(a - abs(endpoint - remote) * drift / 1_000_000 for a, _b, remote in offsets)
        high = min(b + abs(endpoint - remote) * drift / 1_000_000 for _a, b, remote in offsets)
        if low > high or high - low > ceiling:
            raise ValueError("clock_discontinuity_or_uncertainty")
        intervals.append((endpoint + low, endpoint + high))
    return intervals[0][0], intervals[1][1]


class CommitVisibilityProbe:
    """Per-Run total <=256 canonical Events/1MiB; every poll has a fresh snapshot."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        task_id: str,
        run_id: str,
        turn_id: str,
        after_sequence: int,
        budget_seconds: float = 60,
        max_polls: int = 2048,
        clock: Callable[[], float] = _now_ms,
    ) -> None:
        if (
            type(after_sequence) is not int
            or after_sequence < -1
            or not 0 < _number(budget_seconds) <= 60
            or type(max_polls) is not int
            or not 1 <= max_polls <= 2048
            or not isinstance(run_id, str)
            or not 0 < len(run_id) <= 256
        ):
            raise ValueError("invalid_commit_probe_scope_or_budget")
        self.database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self.task_id, self.run_id, self.turn_id = TaskId(UUID(task_id)), run_id, str(UUID(turn_id))
        self.clock, self.clock_id = clock, "commit-probe-" + uuid4().hex
        self.after = after_sequence
        self.deadline = time.monotonic() + budget_seconds
        self.max_polls, self.polls, self.events, self.bytes = max_polls, 0, 0, 0
        self.records: dict[str, dict[str, Any]] = {}
        self.observations: list[dict[str, Any]] = []
        self.absence: tuple[int, float] | None = None
        self.anchor: str | None = None
        self.closed_reason: str | None = None
        self.commentary_coverage = CommentaryCoverage()

    def clock_reading(self) -> dict[str, Any]:
        return {"clock_id": self.clock_id, "reading_ms": _number(self.clock())}

    def _invalid(self, reason: str, sent: float, returned: float) -> dict[str, Any]:
        self.closed_reason = reason
        value = {
            "status": "invalid",
            "reason": reason,
            "send_ms": sent,
            "return_ms": returned,
            "records": [],
        }
        self.observations.append(value)
        return value

    def poll(self) -> dict[str, Any]:
        sent = _number(self.clock())
        if self.closed_reason:
            return {"status": "invalid", "reason": self.closed_reason, "records": []}
        if time.monotonic() >= self.deadline or self.polls >= self.max_polls:
            return self._invalid("probe_deadline_or_poll_limit", sent, sent)
        self.polls += 1
        try:
            with self.database.connect_task_io(
                deadline=min(self.deadline, time.monotonic() + 2)
            ) as c:
                c.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ ONLY")
                header = read_run_header(
                    c, self.database.deployment_namespace, self.task_id, self.run_id, None
                )
                if header.anchor is None:
                    value = {
                        "status": "not_ready",
                        "reason": "canonical_run_not_visible",
                        "send_ms": sent,
                        "return_ms": _number(self.clock()),
                        "records": [],
                    }
                    self.observations.append(value)
                    return value  # Not a miss proof: there is no verified Run window yet.
                if header.control_only:
                    raise ValueError("control_run_has_no_paint_target")
                identity = str(header.anchor.event_id)
                if self.anchor is not None and self.anchor != identity:
                    raise ValueError("canonical_run_anchor_changed")
                if self.anchor is None and self.after >= header.start:
                    raise ValueError("probe_floor_omits_run_window")
                self.anchor = identity
                after = max(self.after, header.start - 1)
                through = (
                    min(header.highwater, header.stop - 1) if header.stop else header.highwater
                )
                if after > through:
                    raise ValueError("probe_floor_omits_run_window")
                if self.events >= MAX_EVENTS or self.bytes >= MAX_BYTES:
                    raise ValueError("per_run_event_or_byte_limit")
                page = read_task_event_page(
                    c,
                    self.database.deployment_namespace,
                    self.task_id,
                    after,
                    limit=MAX_EVENTS - self.events,
                    max_bytes=MAX_BYTES - self.bytes,
                    through=through,
                )
            returned = _number(self.clock())
            if returned < sent:
                raise ValueError("probe_clock_went_backwards")
        except Exception as exc:
            # Database/transport errors can contain credentials or authority payloads.
            reason = (
                str(exc)
                if type(exc) is ValueError
                and str(exc)
                in {
                    "control_run_has_no_paint_target",
                    "canonical_run_anchor_changed",
                    "probe_floor_omits_run_window",
                    "per_run_event_or_byte_limit",
                    "probe_clock_went_backwards",
                }
                else "native_probe_" + type(exc).__name__
            )
            return self._invalid(reason, sent, _number(self.clock()))
        self.events += len(page.events)
        self.bytes += page.byte_count
        found = []
        for entry in page.events:
            self.commentary_coverage.observe(entry)
            if entry.event.event_type not in (EventType.PUBLIC_OUTPUT, EventType.ANSWER_COMMITTED):
                continue
            lower = (
                self.absence[1]
                if self.absence is not None and entry.task_sequence > self.absence[0]
                else None
            )
            record: dict[str, Any] = {
                "status": "measured" if lower is not None else "left_censored",
                "reason": None if lower is not None else "no_prior_complete_absence_snapshot",
                "namespace": self.database.deployment_namespace,
                "task_id": str(self.task_id),
                "run_id": self.run_id,
                "turn_id": self.turn_id,
                "event_id": str(entry.event.event_id),
                "task_sequence": entry.task_sequence,
                "event_type": entry.event.event_type.value,
                "output_id": entry.event.payload.get("output_id"),
                "clock_id": self.clock_id,
                "miss_send_ms": lower,
                "hit_return_ms": returned,
                "commit_interval_ms": None if lower is None else [lower, returned],
            }
            self.records[record["event_id"]] = record
            found.append(record)
        self.after = page.next_sequence
        # A partial page is NOT a complete miss at the captured source highwater.
        if not page.has_more:
            self.absence = (page.highwater, sent)
        value = {
            "status": "hit" if found else "miss" if not page.has_more else "partial",
            "send_ms": sent,
            "return_ms": returned,
            "captured_highwater": page.highwater,
            "covered_through": page.next_sequence,
            "records": found,
        }
        self.observations.append(value)
        return value

    def report(self) -> dict[str, Any]:
        return {
            "schema_version": "zebra.commit-visibility.v1",
            "clock_id": self.clock_id,
            "clock_reading_ms": _number(self.clock()),
            "basis": "read_committed_visibility_bracket",
            "events_read": self.events,
            "bytes_read": self.bytes,
            "polls": self.polls,
            "records": list(self.records.values()),
            "observations": self.observations,
            "invalid_reason": self.closed_reason
            or (
                None
                if self.commentary_coverage.report()["complete"]
                else "commentary_coverage_incomplete"
            ),
            "commentary_coverage": self.commentary_coverage.report(),
            "exact_commit_timestamp": False,
        }


def create_commit_probe(
    config: Config,
    *,
    task_id: str,
    run_id: str,
    turn_id: str,
    after_sequence: int,
    budget_seconds: float = 60,
) -> CommitVisibilityProbe:
    """Production QA seam verifies pinned scratch identity before the first DB read."""
    namespace = joint_preflight(config)["namespace_id"]
    if not isinstance(namespace, str):
        raise ValueError("probe_namespace_unverified")
    verified, _ = task_binding(config, task_id=task_id, simple_slice=True)
    return CommitVisibilityProbe(
        config.zebra_database_dsn,
        deployment_namespace=namespace,
        task_id=verified,
        run_id=run_id,
        turn_id=turn_id,
        after_sequence=after_sequence,
        budget_seconds=budget_seconds,
    )


def persisted_to_paint_interval(
    record: Mapping[str, Any],
    paint: Mapping[str, Any],
    *,
    reference_clock_id: str,
    browser_clock_id: str,
    browser_samples: Sequence[ClockSample],
    drift_ppm: float,
    commit_samples: Sequence[ClockSample] = (),
    max_uncertainty_ms: float = 20,
) -> dict[str, Any]:
    """Existing timing row -> conservative interval; every invalid/left-censored result retained.

    reference_clock_id can be the Node runner's monotonic clock. If the native
    probe runs in Python, calibrate its clock_reading RPCs too; never subtract
    Python monotonic from Node performance.now without that second mapping.
    """
    result = {
        "event_id": record.get("event_id"),
        "task_sequence": record.get("task_sequence"),
        "status": "invalid",
        "reason": None,
        "interval_ms": None,
        "endpoint": "react_commit_then_double_raf_paint_ready_not_physical_presentation",
    }
    try:
        if (
            paint.get("eventId") != record.get("event_id")
            or type(paint.get("sequence")) is not int
            or paint.get("sequence") != record.get("task_sequence")
            or paint.get("turnId") != record.get("turn_id")
            or (
                record.get("output_id") is not None
                and paint.get("outputId") != record.get("output_id")
            )
        ):
            raise ValueError("canonical_paint_identity_mismatch")
        if record.get("status") == "left_censored":
            return {**result, "status": "left_censored", "reason": record.get("reason")}
        if record.get("status") != "measured":
            raise ValueError("commit_record_not_measured")
        if (
            paint.get("replay") is not False
            or paint.get("applied") is not True
            or paint.get("backgrounded") is not False
            or paint.get("coalesced") is True
            or paint.get("paintSuperseded") is True
        ):
            raise ValueError("paint_not_live_or_superseded")
        receipt, react, painted = map(
            _number,
            (
                paint.get("relayReceivedAtMs"),
                paint.get("reactCommittedAtMs"),
                paint.get("paintReadyAtMs"),
            ),
        )
        if not receipt <= react <= painted:
            raise ValueError("paint_stage_order")
        commit_lo, commit_hi = map(_number, record["commit_interval_ms"])
        if commit_lo > commit_hi:
            raise ValueError("commit_bracket_order")
        if record["clock_id"] != reference_clock_id:
            commit_lo, commit_hi = calibrated_clock_interval(
                commit_lo,
                commit_hi,
                remote_clock_id=record["clock_id"],
                reference_clock_id=reference_clock_id,
                samples=commit_samples,
                drift_ppm=drift_ppm,
                max_uncertainty_ms=max_uncertainty_ms,
            )
        visible_lo, visible_hi = calibrated_clock_interval(
            painted,
            painted,
            remote_clock_id=browser_clock_id,
            reference_clock_id=reference_clock_id,
            samples=browser_samples,
            drift_ppm=drift_ppm,
            max_uncertainty_ms=max_uncertainty_ms,
        )
        if visible_hi < commit_lo:
            raise ValueError("paint_precedes_canonical_commit")
        return {
            **result,
            "status": "measured",
            "reason": None,
            "interval_ms": [max(0, visible_lo - commit_hi), visible_hi - commit_lo],
            "commit_interval_reference_ms": [commit_lo, commit_hi],
            "paint_interval_reference_ms": [visible_lo, visible_hi],
            "clock_uncertainty_ms": visible_hi - visible_lo,
            "commit_bracket_width_ms": commit_hi - commit_lo,
            "drift_assumption_ppm": drift_ppm,
            "reference_clock_id": reference_clock_id,
        }
    except (KeyError, TypeError, ValueError) as exc:
        # Only finite contract/classification strings, never raw timing/body exceptions.
        reason = str(exc) if type(exc) is ValueError else "incomplete_measurement_fields"
        return {**result, "reason": reason}


def serve_probe(probe: CommitVisibilityProbe, source: TextIO, target: TextIO) -> None:
    """Bounded NDJSON RPC; Node brackets clock requests with its own send/return clock."""
    for _ in range(4096):
        line = source.readline(8193)
        if not line:
            return
        try:
            if len(line) > 8192 or not line.endswith("\n"):
                raise ValueError("rpc_line_limit")
            request = json.loads(line)
            key = request["request_id"]
            if not isinstance(key, str) or not 0 < len(key) <= 128:
                raise ValueError("rpc_identity")
            operation = request["op"]
            methods = {"clock": probe.clock_reading, "poll": probe.poll, "report": probe.report}
            if operation == "interval":
                arguments = dict(request["arguments"])
                for name in ("browser_samples", "commit_samples"):
                    arguments[name] = [ClockSample(**row) for row in arguments.get(name, [])]
                result = persisted_to_paint_interval(**arguments)
            else:
                result = methods[operation]()
            target.write(json.dumps({"request_id": key, "result": result}, allow_nan=False) + "\n")
            target.flush()
        except Exception as exc:
            target.write(
                json.dumps({"status": "invalid", "reason": "probe_rpc_" + type(exc).__name__})
                + "\n"
            )
            target.flush()
            return
    target.write(json.dumps({"status": "invalid", "reason": "probe_rpc_limit"}) + "\n")
    target.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    for name in ("task-id", "run-id", "turn-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--after-sequence", type=int, required=True)
    args = parser.parse_args()
    try:
        from run_acceptance import REQUIRED_ENV
        from support import load_config

        if args.inputs.stat().st_size > 32768 or args.inputs.stat().st_mode & 0o077:
            raise ValueError("private_bounded_inputs_required")
        inputs = json.loads(args.inputs.read_text())
        for key in ("TRENCH_E2E_BUSINESS_SNAPSHOT_URL", "ZEBRA_E2E_WORKER_RESTART_URL"):
            inputs.setdefault(key, inputs["TRENCH_E2E_BFF_URL"])
        inputs.setdefault("TRENCH_E2E_EVENT_ID", "unused_in_commit_probe")
        probe = create_commit_probe(
            load_config(inputs, REQUIRED_ENV),
            task_id=args.task_id,
            run_id=args.run_id,
            turn_id=args.turn_id,
            after_sequence=args.after_sequence,
        )
        serve_probe(probe, sys.stdin, sys.stdout)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "invalid", "reason": "probe_setup_" + type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
