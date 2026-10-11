"""Synthetic guard tests never count toward actual healthy acceptance samples."""

from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

import pytest
from joint_commit_visibility import ClockSample, persisted_to_paint_interval
from joint_timing import aggregate_timings
from test_joint_public_cases import evidence


def sample(index=0):
    browser = evidence()
    browser.update(conversation_key=f"conversation-{index}", run_id=f"run-{index}")
    browser["timing"]["turns"][0]["submitToFirstMeaningfulCommunicationReceiptMs"] = 200
    browser["timing"]["events"][0].update(
        applied=True, markers=["first_meaningful_task_communication"]
    )
    return {
        "browser": browser,
        "source_identity": {
            role: {"current_checkout_match": True, "python_src_sha256": "digest", "image_id": role}
            for role in ("worker", "zebra_api", "broker")
        },
    }


def test_complete_browser_distribution_does_not_claim_cross_clock_or_full_goal():
    result = aggregate_timings([sample(index) for index in range(100)])
    assert result["browser_timing_passed"] is True
    assert result["persisted_to_visible"]["status"] == "unmeasured"
    assert result["full_goal_passed"] is False


def test_faults_and_missing_meaningful_evidence_cannot_fill_sample_quota():
    samples = [sample(index) for index in range(100)]
    samples[0]["fault"] = "provider_timeout"
    assert aggregate_timings(samples)["healthy_samples"] == 99
    assert aggregate_timings(samples)["browser_timing_passed"] is False
    samples[0].pop("fault")
    samples[0]["browser"]["timing"]["events"][0]["markers"] = []
    result = aggregate_timings(samples)
    assert result["browser_timing_passed"] is False
    assert result["missing_measurements"] == ["meaningful_communication:run-0"]


def test_duplicate_and_mixed_source_samples_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_timings([sample(), sample()])
    second = sample(1)
    second["source_identity"]["worker"]["python_src_sha256"] = "different"
    with pytest.raises(ValueError, match="mixed_source"):
        aggregate_timings([sample(), second])


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf")])
def test_invalid_timing_is_rejected(value):
    row = sample()
    row["browser"]["timing"]["turns"][0]["submitToAdmissionFeedbackMs"] = value
    with pytest.raises(ValueError):
        aggregate_timings([row])


def test_worst_frame_per_run_prevents_many_fast_frames_hiding_delays():
    samples = [sample(index) for index in range(100)]
    for row in samples:
        slow = deepcopy(row["browser"]["timing"]["events"][0])
        slow["relayToPaintReadyMs"] = 501
        row["browser"]["timing"]["events"].append(slow)
    result = aggregate_timings(samples)
    assert result["metrics"]["relayToPaintReadyMs"]["p95"] == 501
    assert result["browser_timing_passed"] is False


def calibrated_sample(index=0):
    value = sample(index)
    browser = value["browser"]
    browser["timing"]["timeOriginMs"] = 123
    frames = browser["frames"]
    records = []
    for position, kind in ((21, "public_output"), (23, "answer_committed")):
        event_id = str(uuid4())
        record = dict(
            event_id=event_id,
            task_sequence=position,
            event_type=kind,
            run_id=browser["run_id"],
            turn_id=browser["turn_id"],
            task_id=str(uuid4()),
            status="measured",
            clock_id="python",
            commit_interval_ms=[40, 50],
        )
        records.append(record)
        if kind == "public_output":
            frames[0].update(event_id=event_id, sequence=position)
            paint = browser["timing"]["events"][0]
            paint.update(
                type="public_output",
                eventId=event_id,
                sequence=position,
                relayReceivedAtMs=55,
                reactCommittedAtMs=58,
                paintReadyAtMs=60,
            )
        else:
            frames.append(
                dict(
                    type="answer_reset",
                    cursor=2,
                    event_id=event_id,
                    sequence=position,
                    answer_committed=True,
                )
            )
            browser["timing"]["events"].append(
                dict(
                    type="answer_reset",
                    eventId=event_id,
                    sequence=position,
                    turnId=browser["turn_id"],
                    replay=False,
                    applied=True,
                    backgrounded=False,
                    relayReceivedAtMs=75,
                    reactCommittedAtMs=78,
                    paintReadyAtMs=80,
                    markers=["final_answer_committed"],
                    relayToPaintReadyMs=15,
                )
            )
    calibration = {
        name: [
            asdict(ClockSample("node", clock, 110, 10, 112, 0)),
            asdict(ClockSample("node", clock, 190, 90, 192, 0)),
        ]
        for name, clock in (("commit", "python"), ("browser", "page:123"))
    }
    calibration.update(drift_assumption_ppm=0, max_uncertainty_ms=20)
    browser["commit_visibility"] = dict(
        schema_version="zebra.browser-commit-visibility.v1",
        complete=True,
        run_id=browser["run_id"],
        turn_id=browser["turn_id"],
        total_targets=2,
        invalids=[],
        native=dict(records=records),
        reference_clock_id="node",
        calibration=calibration,
    )
    recompute(value)
    return value


def recompute(value):
    browser = value["browser"]
    report = browser["commit_visibility"]
    calibration = report["calibration"]
    report["results"] = [
        persisted_to_paint_interval(
            record,
            next(
                paint
                for paint in browser["timing"]["events"]
                if paint["eventId"] == record["event_id"]
            ),
            reference_clock_id="node",
            browser_clock_id="page:123",
            browser_samples=[ClockSample(**row) for row in calibration["browser"]],
            commit_samples=[ClockSample(**row) for row in calibration["commit"]],
            drift_ppm=0,
        )
        for record in report["native"]["records"]
    ]


def test_100_complete_runs_use_worst_calibrated_upper_not_midpoint_or_frame_weighting():
    result = aggregate_timings([calibrated_sample(index) for index in range(100)])
    assert result["persisted_to_visible"]["count"] == 100
    assert result["persisted_to_visible"]["p95_upper_ms"] == 42
    assert result["persisted_to_visible"]["passed"] is True
    assert result["timing_passed"] is True and result["full_goal_passed"] is False


def test_99_complete_or_one_incomplete_among_over_100_cannot_claim_distribution():
    values = [calibrated_sample(index) for index in range(101)]
    assert aggregate_timings(values[:99])["persisted_to_visible"]["passed"] is False
    values[-1]["browser"]["commit_visibility"]["complete"] = False
    result = aggregate_timings(values)
    assert result["functional_evidence_passed"] is True
    assert result["browser_timing_passed"] is True
    assert result["persisted_to_visible"]["count"] == 100
    assert result["persisted_to_visible"]["passed"] is False
    assert len(result["persisted_to_visible"]["incomplete_samples"]) == 1


@pytest.mark.parametrize(
    "bad",
    [
        "censored",
        "forged_upper",
        "missing_target",
        "missing_frame",
        "clock_reset",
        "unknown_publication",
        "final_marker",
        "replay",
    ],
)
def test_complete_flag_alone_cannot_hide_invalid_or_omitted_evidence(bad):
    value = calibrated_sample()
    browser = value["browser"]
    report = browser["commit_visibility"]
    if bad == "censored":
        report["native"]["records"][0]["status"] = "left_censored"
    elif bad == "forged_upper":
        report["results"][0]["interval_ms"] = [0, 1]
    elif bad == "missing_target":
        report["results"].pop()
    elif bad == "missing_frame":
        browser["frames"].pop()
    elif bad == "clock_reset":
        browser["timing"]["timeOriginMs"] = 124
    elif bad == "unknown_publication":
        browser["frames"].append(
            dict(type="public_update", cursor=3, event_id=str(uuid4()), sequence=25)
        )
    elif bad == "final_marker":
        browser["timing"]["events"][-1]["markers"] = []
    else:
        browser["timing"]["events"][-1]["replay"] = True
    result = aggregate_timings([value])
    assert result["persisted_to_visible"]["count"] == 0
    assert len(result["persisted_to_visible"]["incomplete_samples"]) == 1
    assert result["functional_evidence_passed"] is True
    assert result["timing_passed"] is False


def test_slow_upper_bounds_fail_slo_without_failing_functional_or_browser_receipt_metrics():
    values = [calibrated_sample(index) for index in range(100)]
    for value in values:
        browser = value["browser"]
        browser["timing"]["events"][-1].update(
            relayReceivedAtMs=1050, reactCommittedAtMs=1055, paintReadyAtMs=1060
        )
        calibration = browser["commit_visibility"]["calibration"]
        for name in ("browser", "commit"):
            calibration[name][-1].update(send_ms=1390, remote_ms=1290, return_ms=1392)
        recompute(value)
    result = aggregate_timings(values)
    assert result["persisted_to_visible"]["p95_upper_ms"] == 1022
    assert result["persisted_to_visible"]["passed"] is False
    assert result["functional_evidence_passed"] is True
    assert result["browser_timing_passed"] is True
