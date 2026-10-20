"""A passing pytest exit cannot hide skipped or empty conformance runs."""

import pytest

from tests.conformance.product_v1.run import complete, counts


@pytest.mark.parametrize(
    "body,exit_code,accepted",
    [
        ('<testcase name="read"/>', 0, True),
        ('<testcase><skipped message="no external DB"/></testcase>', 0, False),
        ("<testcase><failure/></testcase>", 0, False),
        ("<testcase><error/></testcase>", 0, False),
        ("", 0, False),
        ("<testcase/>", 1, False),
    ],
)
def test_gate_requires_executed_checks_without_skips(tmp_path, body, exit_code, accepted):
    report = tmp_path / "junit.xml"
    report.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    assert complete(counts(report), exit_code) is accepted


def _runner(monkeypatch, tmp_path, outcome="complete"):
    import json
    import sys
    from types import SimpleNamespace

    from tests.conformance.product_v1 import run

    monkeypatch.setattr(run, "CONTRACT_TESTS", ("tests/test_a.py", "tests/test_b.py"))
    monkeypatch.setattr(sys, "argv", ["conformance", "--evidence-dir", str(tmp_path)])
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k only_one_case")
    verdict = tmp_path / "conformance-result.json"
    verdict.write_text(json.dumps({"status": "PASS", "tests": 999}))

    def execute(command, **kwargs):
        assert json.loads(verdict.read_text())["status"] == "FAIL"
        assert "PYTEST_ADDOPTS" not in kwargs["env"]
        if outcome == "launch_error":
            raise OSError("private transport detail")
        if outcome == "interrupt":
            raise KeyboardInterrupt
        report = tmp_path / "junit.xml"
        if outcome == "bad_xml":
            report.write_text("<incomplete")
        else:
            second = '<testcase classname="tests.test_b"/>' if outcome == "complete" else ""
            report.write_text(
                '<testsuites><testsuite><testcase classname="tests.test_a"/>'
                + second
                + "</testsuite></testsuites>"
            )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run.subprocess, "run", execute)
    return run, verdict


@pytest.mark.parametrize("outcome", ["complete", "subset", "launch_error", "bad_xml", "interrupt"])
def test_runner_cannot_publish_partial_or_stale_pass(tmp_path, monkeypatch, outcome):
    import json

    run, verdict = _runner(monkeypatch, tmp_path, outcome)
    if outcome == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            run.main()
    else:
        assert run.main() == (0 if outcome == "complete" else 1)
    result = json.loads(verdict.read_text())
    assert result["status"] == ("PASS" if outcome == "complete" else "FAIL")
    if outcome == "subset":
        assert result["missing_modules"] == ["tests.test_b"]


def test_auxiliary_result_does_not_poison_release_discovery(tmp_path, monkeypatch):
    import json
    import sys

    from scripts import build_release_evidence
    from tests.conformance.product_v1.run import ROOT

    legacy = {"schema": "overdoze.product-conformance.v1", "status": "PASS"}
    (tmp_path / "result.json").write_text(json.dumps(legacy))
    with monkeypatch.context() as patch:
        run, _ = _runner(patch, tmp_path)
        assert run.main() == 0
    assert not (tmp_path / "result.json").exists()
    assert json.loads((tmp_path / "legacy-conformance-result.json").read_text()) == legacy
    output = tmp_path / "release-manifest.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release-evidence",
            "--capabilities",
            str(ROOT / "configs/cloud_release_capabilities.example.json"),
            "--evidence-root",
            str(tmp_path),
            "--output",
            str(output),
        ],
    )
    # Missing real release evidence must FAIL, but auxiliary conformance is not a gate envelope.
    assert build_release_evidence.main() == 1
    assert json.loads(output.read_text())["status"] == "FAIL"
