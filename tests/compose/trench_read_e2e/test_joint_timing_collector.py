"""Collector guards only; mocked runs never establish actual acceptance."""

import json

import joint_timing_collector as collector
import pytest
from test_joint_timing import calibrated_sample, sample


def test_failed_first_run_stops_without_claiming_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "validate_seed", lambda _: None)
    calls = []

    def blocked(environment, destination, **kwargs):
        calls.append(kwargs["case_id"])
        destination.mkdir()
        (destination / "joint-result.json").write_text(
            json.dumps({"status": "blocked", "reason": "catalog_unavailable"})
        )

    monkeypatch.setattr(collector, "run_joint", blocked)
    output = tmp_path / "evidence"
    assert collector.collect(output, {}) == 2
    result = json.loads((output / "timing-summary.json").read_text())
    assert calls == ["multi_source"]
    assert result["healthy_samples"] == 0 and result["full_goal_passed"] is False


@pytest.mark.parametrize("calibrated", [False, True])
def test_incremental_cohort_cycles_business_cases_and_bounds_each_run(
    tmp_path, monkeypatch, calibrated
):
    monkeypatch.setattr(collector, "validate_seed", lambda _: None)
    calls = []

    def successful(environment, destination, **kwargs):
        assert environment["ZEBRA_E2E_COMMIT_VISIBILITY"] == "1"
        assert 5 <= int(environment["ZEBRA_E2E_TIMEOUT_SECONDS"]) <= 300
        row = (calibrated_sample if calibrated else sample)(len(calls))
        case = kwargs["case_id"]
        calls.append(case)
        destination.mkdir()
        (destination / "joint-result.json").write_text(
            json.dumps({"status": "slice_passed", "source_identity": row["source_identity"]})
        )
        (destination / (case.replace("_", "-") + ".json")).write_text(json.dumps(row["browser"]))

    monkeypatch.setattr(collector, "run_joint", successful)
    output = tmp_path / "evidence"
    assert collector.collect(output, {}) == (0 if calibrated else 2)
    result = json.loads((output / "timing-summary.json").read_text())
    assert result["healthy_samples"] == 100 and result["full_goal_passed"] is False
    assert result["browser_timing_passed"] is True
    assert result["timing_passed"] is calibrated
    assert set(calls) == {"multi_source", "tool_only"}
    assert calls.count("multi_source") == calls.count("tool_only") == 50
