"""Fault evidence contract checks, never real-model/browser acceptance."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from joint_fault_cases import fault_prompt, operate_fault, run_fault_case, validate_fault
from support import E2EError
from test_joint_public_cases import evidence as browser_evidence

from tests.agent_core.test_public_output import verified_facts


def point(sequence, kind, **fields):
    return {
        "task_sequence": sequence,
        "event_type": kind,
        "event_id": f"source-{sequence}",
        **fields,
    }


def sample(case_id="slow_execution"):
    summary = "Read 20 records; this is only a partial sample, not full coverage."
    facts = verified_facts(summary)
    rows = [
        point(1, "model_request_started", policy={"wait_seconds": 1}),
        point(2, "model_response_received", provider="deepseek", request_hash="a" * 64),
        point(3, "tool_execution_started", tool_call_id="first", tool_name="events.search_history"),
        point(4, "tool_execution_completed", tool_call_id="first", status="executed", facts=facts),
        point(
            5,
            "public_output",
            output_id="initial",
            phase="evidence",
            meaningful=True,
            basis="verified_result",
            refs=["first"],
            content=summary,
        ),
        point(6, "tool_execution_started", tool_call_id="slow", tool_name="events.search_history"),
        point(7, "tool_execution_started", tool_call_id="fast", tool_name="sources.list"),
        point(8, "tool_execution_completed", tool_call_id="fast", status="executed", facts=facts),
        point(
            9,
            "public_output",
            output_id="during",
            phase="evidence",
            meaningful=True,
            basis="verified_result",
            refs=["fast"],
            content=summary,
        ),
        point(
            10,
            "public_output",
            output_id="wait",
            phase="waiting",
            meaningful=False,
            refs=[],
            content="Still waiting for the current operation; no new confirmed result.",
        ),
        point(11, "tool_execution_completed", tool_call_id="slow", status="executed"),
        point(13, "answer_committed"),
    ]
    if case_id == "partial_failure":
        rows[-2] = point(11, "tool_execution_failed", tool_call_id="slow", reason="timeout")
        rows.insert(
            -1,
            point(
                12,
                "public_output",
                output_id="failure",
                phase="recovery",
                meaningful=False,
                refs=["slow"],
                content="No successful receipt.",
            ),
        )
    browser = browser_evidence()
    browser.update(case_id=case_id, task_id="task-1", run_id="run-1")
    browser["frames"] = [
        {
            "cursor": index + 1,
            "type": "public_output",
            "output_id": row["output_id"],
            "event_id": row["event_id"],
            "meaningful": row["meaningful"],
            "content_sha256": sha256(row["content"].encode()).hexdigest(),
        }
        for index, row in enumerate(rows)
        if row["event_type"] == "public_output"
    ]
    browser["fault_visibility"] = [
        {"output_id": frame["output_id"], "before_terminal": True, "before_final_receipt": True}
        for frame in browser["frames"]
    ]
    browser["operator"] = {
        "schema_version": "zebra.joint-sql-fault.v1",
        "scope": "actual_scratch_business_sql_lock",
        "provider_or_receipt_injection": False,
        "case_id": case_id,
        "task_id": "task-1",
        "run_id": "run-1",
        "armed_after_sequence": 5,
        "target_call_id": "slow",
        "started_sequence": 6,
        "terminal_sequence": 11,
        "blocked_on_business_sql": True,
        "holder_closed": True,
        "backend_gone": True,
        "business_unchanged": True,
    }
    native = {
        "task_id": "task-1",
        "run_id": "run-1",
        "host_thread": "opaque-host",
        "scope": "canonical_run_headers_and_public_points",
        "points": rows,
    }
    return browser, native


@pytest.mark.parametrize("case_id", ["slow_execution", "partial_failure"])
def test_fault_requires_real_source_and_live_visibility(case_id):
    browser, native = sample(case_id)
    validate_fault(browser, native)
    browser["fault_visibility"] = []
    with pytest.raises(E2EError, match="not_visible"):
        validate_fault(browser, native)


@pytest.mark.parametrize(
    "field,value",
    [
        ("blocked_on_business_sql", False),
        ("holder_closed", False),
        ("backend_gone", False),
        ("business_unchanged", False),
        ("provider_or_receipt_injection", True),
        ("run_id", "other"),
    ],
)
def test_unproved_fault_or_cleanup_is_not_live_acceptance(field, value):
    browser, native = sample()
    browser["operator"][field] = value
    with pytest.raises(E2EError):
        validate_fault(browser, native)


@pytest.mark.parametrize("defect", ["provider", "wait_meaningful", "wait_terminal", "no_flush"])
def test_slow_case_preserves_real_provider_and_operation_causality(defect):
    browser, native = sample()
    rows = native["points"]
    if defect == "provider":
        rows[1]["provider"] = "fixture"
    elif defect == "wait_meaningful":
        rows[9]["meaningful"] = True
    elif defect == "wait_terminal":
        rows[9]["task_sequence"] = 12
        rows.sort(key=lambda row: row["task_sequence"])
    else:
        rows[8]["refs"] = ["first"]
    with pytest.raises(E2EError):
        validate_fault(browser, native)


@pytest.mark.parametrize(
    "defect", ["invented_success", "failure_reason", "recovery_ref", "lost_fact"]
)
def test_partial_failure_keeps_success_and_truthful_failure_separate(defect):
    browser, native = sample("partial_failure")
    rows = native["points"]
    if defect == "invented_success":
        rows[10]["event_type"] = "tool_execution_completed"
        rows[10]["status"] = "executed"
    elif defect == "failure_reason":
        rows[10]["reason"] = "missing_argument"
    elif defect == "recovery_ref":
        rows[11]["refs"] = ["other"]
    else:
        rows[4]["content"] = "Successfully read all records."
    with pytest.raises(E2EError):
        validate_fault(browser, native)


def test_browser_identity_and_hash_must_match_native_public_event():
    browser, native = sample()
    browser["frames"][0]["content_sha256"] = "0" * 64
    with pytest.raises(E2EError, match="not_visible"):
        validate_fault(browser, native)
    browser, native = sample()
    native["points"].append(deepcopy(native["points"][-1]))
    with pytest.raises(E2EError):
        validate_fault(browser, native)


def test_prompt_requests_real_reads_not_provider_or_receipt_injection():
    seed = {
        "seed_id": "a" * 16,
        "source_ids": ["b" * 32, "c" * 32],
        "event_ids": [f"{i:032x}" for i in range(48)],
        "event_count": 48,
        "per_source_count": 24,
        "scope": "actual_scratch_business_rows",
        "provider_or_receipt_injection": False,
    }
    prompt = fault_prompt("slow_execution", "ZEBRA_QA_SIMPLE_" + "a" * 32, seed)
    assert "events.search_history" in prompt and "sources.list" in prompt
    assert "不要修改" in prompt and "覆盖" in prompt
    with pytest.raises(E2EError, match="unimplemented"):
        fault_prompt("image", "marker", seed)


def test_unfrozen_build_cannot_launch_fault_or_be_marked_live(tmp_path, monkeypatch):
    monkeypatch.setattr("joint_fault_cases.subprocess.run", lambda *_a, **_k: pytest.fail("launch"))
    with pytest.raises(E2EError, match="freeze_required"):
        run_fault_case(None, {}, tmp_path, case_id="slow_execution", seed={})


@pytest.mark.parametrize(
    "primary", [RuntimeError("lock failure"), asyncio.CancelledError("original")]
)
def test_operator_close_preserves_primary_base_exception(monkeypatch, primary):
    """Connection fault protocol regression, not a provider or live acceptance fixture."""
    _, native = sample()
    native["points"] = native["points"][:5]
    closed = []

    def execute(_sql):
        raise primary

    def close():
        closed.append(True)
        raise asyncio.CancelledError("secondary close")

    holder = SimpleNamespace(info=SimpleNamespace(backend_pid=123), execute=execute, close=close)
    monkeypatch.setattr("joint_fault_cases.joint_preflight", lambda _: {"namespace_id": "scratch"})
    monkeypatch.setattr("joint_fault_cases.business_snapshot", lambda _: "unchanged")
    monkeypatch.setattr("joint_fault_cases.native_fault_points", lambda *_: native)
    monkeypatch.setattr(
        "agent_storage.postgres.database.PostgresDatabase",
        lambda *_a, **_k: SimpleNamespace(connect_task_io=lambda: holder),
    )
    config = SimpleNamespace(
        trench_database_dsn="postgresql://localhost/scratch_trench", timeout_seconds=1
    )
    with pytest.raises(type(primary)) as caught:
        operate_fault(config, case_id="slow_execution", conversation_key="c", run_id="run-1")
    assert caught.value is primary
    assert closed == [True]
    assert any("cleanup" in note for note in primary.__notes__)
