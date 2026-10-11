"""Fail-closed aggregation of actual healthy browser runs, not fixture acceptance."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

from joint_acceptance import validate_live_evidence
from joint_commit_coverage import require_commentary_coverage
from joint_commit_visibility import ClockSample, persisted_to_paint_interval

LIMITS = {
    "submitToAdmissionFeedbackMs": 1000,
    "submitToFirstMeaningfulCommunicationReceiptMs": 8000,
    "relayToPaintReadyMs": 500,
}
COMMIT_LIMIT_MS = 1000


def _commit_upper(evidence: Mapping[str, Any]) -> float:
    """Recompute every canonical target's bounds; never trust a complete flag alone."""
    report = evidence["commit_visibility"]
    require_commentary_coverage(report["native"])
    rows = report["results"]
    records = report["native"]["records"]
    if (
        report["schema_version"] != "zebra.browser-commit-visibility.v1"
        or report["complete"] is not True
        or report["run_id"] != evidence["run_id"]
        or report["turn_id"] != evidence["turn_id"]
        or report["invalids"]
        or report["native"].get("invalid_reason")
        or type(report["total_targets"]) is not int
        or not 1 <= report["total_targets"] <= 256
        or len(rows) != report["total_targets"]
        or len(records) != len(rows)
    ):
        raise ValueError("incomplete_commit_visibility")
    calibration = report["calibration"]
    browser_samples = [ClockSample(**row) for row in calibration["browser"]]
    commit_samples = [ClockSample(**row) for row in calibration["commit"]]
    origin = _number(evidence["timing"]["timeOriginMs"])
    clock_id = "page:" + (str(int(origin)) if origin.is_integer() else str(origin))
    if browser_samples[0].remote_clock_id != clock_id:
        raise ValueError("browser_clock_identity_mismatch")
    by_key = {(record["event_id"], record["task_sequence"]): record for record in records}
    if len(by_key) != len(records):
        raise ValueError("duplicate_commit_source")
    publications = set()
    for frame in evidence["frames"]:
        if frame.get("type") == "public_output" or (
            frame.get("type") == "answer_reset" and frame.get("answer_committed") is True
        ):
            publications.add((frame.get("event_id"), frame.get("sequence")))
        elif (
            frame.get("type")
            not in {
                "meta",
                "agent_step",
                "tool_start",
                "tool_result",
                "thinking",
                "delta",
                "answer_reset",
                "done",
            }
            or frame.get("meaningful") is True
            or frame.get("answer_committed") is True
        ):
            raise ValueError("unknown_publication_frame")
    if publications != set(by_key):
        raise ValueError("missing_canonical_publication")
    seen, upper = set(), []
    for row in rows:
        key = row["event_id"], row["task_sequence"]
        record = by_key[key]
        if (
            key in seen
            or row["status"] != "measured"
            or record["status"] != "measured"
            or record["event_type"] not in {"public_output", "answer_committed"}
            or record["run_id"] != evidence["run_id"]
            or record["turn_id"] != evidence["turn_id"]
        ):
            raise ValueError("invalid_commit_target")
        seen.add(key)
        publication = record["event_type"] == "public_output"
        frames = [
            frame
            for frame in evidence["frames"]
            if (frame.get("event_id"), frame.get("sequence")) == key
            and frame.get("type") == ("public_output" if publication else "answer_reset")
            and (publication or frame.get("answer_committed") is True)
        ]
        paints = [
            paint
            for paint in evidence["timing"]["events"]
            if (paint.get("eventId"), paint.get("sequence")) == key
            and paint.get("turnId") == evidence["turn_id"]
            and paint.get("type") == ("public_output" if publication else "answer_reset")
        ]
        if len(frames) != 1 or len(paints) != 1:
            raise ValueError("missing_or_ambiguous_commit_provenance")
        if not publication and "final_answer_committed" not in paints[0].get("markers", []):
            raise ValueError("authoritative_final_unproven")
        computed = persisted_to_paint_interval(
            record,
            paints[0],
            reference_clock_id=report["reference_clock_id"],
            browser_clock_id=browser_samples[0].remote_clock_id,
            browser_samples=browser_samples,
            commit_samples=commit_samples,
            drift_ppm=calibration["drift_assumption_ppm"],
            max_uncertainty_ms=calibration["max_uncertainty_ms"],
        )
        if computed["status"] != "measured" or computed["interval_ms"] != row["interval_ms"]:
            raise ValueError("commit_bounds_unverified")
        upper.append(_number(computed["interval_ms"][1]))
    return max(upper)  # One worst upper bound per run, not many fast frames per slow run.


def _number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid_timing_measurement")
    return float(value)


def aggregate_timings(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Each item holds browser evidence and the independently verified source identity.

    Fault runs are retained separately. A missing meaningful output remains missing;
    it cannot be replaced by an acceptance, heartbeat, final answer or generic text.
    Persisted-to-visible needs an independently calibrated cross-clock measurement.
    """
    measurements: dict[str, list[float]] = {name: [] for name in LIMITS}
    faults: list[str] = []
    missing: list[str] = []
    seen: set[tuple[str, str]] = set()
    identity: Mapping[str, Any] | None = None
    healthy = 0
    commit_values: list[float] = []
    commit_incomplete: list[dict[str, Any]] = []
    for sample in samples:
        source = sample.get("source_identity")
        if not isinstance(source, Mapping) or not all(
            isinstance(source.get(role), Mapping)
            and source[role].get("current_checkout_match") is True
            and isinstance(source[role].get("python_src_sha256"), str)
            and bool(source[role]["python_src_sha256"])
            for role in ("worker", "zebra_api", "broker")
        ):
            raise ValueError("latest_source_not_verified")
        if identity is None:
            identity = source
        elif source != identity:
            raise ValueError("mixed_source_identity")
        evidence = sample.get("browser")
        if not isinstance(evidence, Mapping):
            raise ValueError("browser_evidence_missing")
        key = (evidence.get("conversation_key"), evidence.get("run_id"))
        if any(not isinstance(value, str) or not value for value in key) or key in seen:
            raise ValueError("duplicate_or_missing_run_identity")
        key = cast(tuple[str, str], key)
        seen.add(key)
        fault = sample.get("fault")
        if fault is not None:
            if not isinstance(fault, str) or not fault:
                raise ValueError("invalid_fault_classification")
            faults.append(fault)
            continue
        validate_live_evidence(evidence)
        timing = evidence["timing"]
        turn = next(row for row in timing["turns"] if row.get("turnId") == evidence["turn_id"])
        events = [
            row
            for row in timing["events"]
            if row.get("turnId") == evidence["turn_id"]
            and row.get("replay") is False
            and row.get("applied") is True
            and row.get("backgrounded") is False
            and row.get("coalesced") is not True
            and row.get("paintSuperseded") is not True
        ]
        healthy += 1
        try:
            commit_values.append(_commit_upper(evidence))
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            commit_incomplete.append(
                {
                    "run_id": key[1],
                    "status": "incomplete",
                    "reason": "missing_or_invalid_calibrated_commit_visibility",
                }
            )
        measurements["submitToAdmissionFeedbackMs"].append(
            _number(turn["submitToAdmissionFeedbackMs"])
        )
        meaningful = turn.get("submitToFirstMeaningfulCommunicationReceiptMs")
        if (
            meaningful is None
            or turn.get("firstMeaningfulCommunicationReplay") is True
            or turn.get("firstMeaningfulCommunicationRestored") is True
            or not any(
                "first_meaningful_task_communication" in row.get("markers", []) for row in events
            )
        ):
            missing.append("meaningful_communication:" + key[1])
        else:
            measurements["submitToFirstMeaningfulCommunicationReceiptMs"].append(
                _number(meaningful)
            )
        painted = [row for row in events if row.get("relayToPaintReadyMs") is not None]
        if not painted:
            missing.append("paint_ready:" + key[1])
        else:
            # One worst observed frame per run prevents many fast frames masking a slow run.
            measurements["relayToPaintReadyMs"].append(
                max(_number(row["relayToPaintReadyMs"]) for row in painted)
            )
    stats = {}
    for name, values in measurements.items():
        ordered = sorted(values)
        p95 = ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None
        stats[name] = {
            "count": len(values),
            "p95": p95,
            "limit": LIMITS[name],
            "passed": len(values) >= 100 and p95 is not None and p95 <= LIMITS[name],
        }
    ordered_commit = sorted(commit_values)
    commit_p95 = (
        ordered_commit[math.ceil(len(ordered_commit) * 0.95) - 1] if ordered_commit else None
    )
    commit_passed = (
        healthy >= 100
        and not commit_incomplete
        and len(commit_values) == healthy
        and commit_p95 is not None
        and commit_p95 <= COMMIT_LIMIT_MS
    )
    browser_passed = healthy >= 100 and not missing and all(row["passed"] for row in stats.values())
    return {
        "healthy_samples": healthy,
        "required_healthy_samples": 100,
        "fault_samples": faults,
        "missing_measurements": missing,
        "metrics": stats,
        "functional_evidence_passed": healthy > 0,
        "browser_timing_passed": browser_passed,
        "persisted_to_visible": {
            "status": "unmeasured"
            if not commit_values
            else "incomplete"
            if commit_incomplete
            else "measured",
            "count": len(commit_values),
            "required_healthy_samples": 100,
            "p95_upper_ms": commit_p95,
            "limit_ms": COMMIT_LIMIT_MS,
            "passed": commit_passed,
            "incomplete_samples": commit_incomplete,
            "basis": "worst_per_run_calibrated_interval_upper_bound_to_double_raf",
            "physical_presentation": False,
        },
        "timing_passed": browser_passed and commit_passed,
        "full_goal_passed": False,
    }
