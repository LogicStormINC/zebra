"""Takeover evidence rejection tests, not real browser/provider acceptance."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from joint_worker_takeover import host_worker_restart, takeover_prompt, validate_takeover
from support import E2EError
from test_joint_public_cases import evidence

from tests.agent_core.test_public_output import verified_facts


def sample():
    summary = "Read 20 records; partial sample, not full coverage."
    rows = [
        {
            "task_sequence": 1,
            "event_id": "e1",
            "event_type": "harness_attempt_started",
            "attempt": 1,
        },
        {"task_sequence": 2, "event_id": "e2", "event_type": "model_request_started"},
        {
            "task_sequence": 3,
            "event_id": "e3",
            "event_type": "model_response_received",
            "provider": "deepseek",
            "request_hash": "a" * 64,
            "repair_count": 0,
        },
        {"task_sequence": 4, "event_id": "e4", "event_type": "tool_execution_started", "call": "a"},
        {
            "task_sequence": 5,
            "event_id": "e5",
            "event_type": "tool_execution_completed",
            "call": "a",
            "status": "executed",
            "facts": verified_facts(summary),
        },
        {
            "task_sequence": 6,
            "event_id": "e6",
            "event_type": "public_output",
            "output": "o1",
            "phase": "evidence",
            "refs": ["a"],
            "meaningful": True,
            "basis": "verified_result",
            "content": summary,
        },
        {"task_sequence": 7, "event_id": "e7", "event_type": "model_request_started"},
        {"task_sequence": 8, "event_id": "e8", "event_type": "model_request_started"},
        {
            "task_sequence": 9,
            "event_id": "e9",
            "event_type": "model_response_received",
            "provider": "deepseek",
            "request_hash": "b" * 64,
            "repair_count": 0,
        },
        {"task_sequence": 10, "event_id": "e10", "event_type": "answer_committed"},
    ]
    before = {
        "task_id": "task",
        "run_id": "run",
        "anchor_id": "anchor",
        "segment": "segment",
        "budget": {"max_model_calls": 4, "max_tool_calls": 3},
        "attempt": 1,
        "lease": {"epoch": "epoch", "token": 3, "owner": "worker", "checkpoint": 4, "active": True},
        "rows": deepcopy(rows[:7]),
    }
    after = {
        **deepcopy(before),
        "status": "awaiting_turn",
        "rows": rows,
        "lease": {
            "epoch": "epoch",
            "token": 4,
            "owner": "worker",
            "checkpoint": 9,
            "active": False,
        },
    }
    browser = evidence()
    browser.update(case_id="worker_takeover", run_id="run", healthy_samples=0)
    browser["operator"] = {
        "schema_version": "zebra.joint-takeover.v1",
        "scope": "actual_scratch_operator_restart",
        "provider_or_receipt_injection": False,
        "task_id": "task",
        "run_id": "run",
        "before": before,
        "after": after,
        "restart_accepted": True,
        "business_unchanged": True,
        "process_before": {"started_at": "old", "host_pid": 10},
        "process_after": {"started_at": "new", "host_pid": 20},
        "worker_before": {"coverage_complete": True, "execution_threads": 1, "model_threads": 1},
    }
    return browser, after


def test_real_takeover_contract_allows_recovery_of_the_same_attempt():
    browser, native = sample()
    validate_takeover(browser, native)
    assert browser["operator"]["before"]["attempt"] == native["attempt"]


@pytest.mark.parametrize(
    "defect",
    [
        "restart",
        "process",
        "fence",
        "checkpoint",
        "budget",
        "prefix",
        "provider",
        "duplicate_tool",
        "milestone",
        "final",
        "attempt",
        "active_execution",
        "fake",
        "run",
        "unlimited",
    ],
)
def test_takeover_never_accepts_flags_without_canonical_recovery(defect):
    browser, native = sample()
    operator = browser["operator"]
    if defect == "restart":
        operator["restart_accepted"] = False
    elif defect == "process":
        operator["process_after"] = deepcopy(operator["process_before"])
    elif defect == "fence":
        native["lease"]["token"] = 3
    elif defect == "checkpoint":
        native["lease"]["checkpoint"] = 3
    elif defect == "budget":
        native["budget"]["max_model_calls"] = 8
    elif defect == "prefix":
        native["rows"][1]["event_id"] = "substituted"
    elif defect == "provider":
        native["rows"][8]["provider"] = "fake"
    elif defect == "duplicate_tool":
        native["rows"][-1]["task_sequence"] = 11
        native["rows"].insert(
            -1,
            {
                "task_sequence": 10,
                "event_id": "dupe",
                "event_type": "tool_execution_started",
                "call": "a",
            },
        )
    elif defect == "milestone":
        native["rows"][-1]["task_sequence"] = 11
        native["rows"].insert(
            -1,
            {
                "task_sequence": 10,
                "event_id": "repeat",
                "event_type": "public_output",
                "output": "o2",
                "phase": "evidence",
                "refs": ["a"],
            },
        )
    elif defect == "final":
        native["rows"][-1]["event_type"] = "session_failed"
    elif defect == "attempt":
        native["attempt"] = 0
    elif defect == "active_execution":
        operator["worker_before"]["model_threads"] = 0
    elif defect == "fake":
        operator["provider_or_receipt_injection"] = True
    elif defect == "unlimited":
        operator["before"]["budget"]["max_model_calls"] = None
        native["budget"]["max_model_calls"] = None
    else:
        operator["run_id"] = "other"
    with pytest.raises((E2EError, ValueError)):
        validate_takeover(browser, native)


@pytest.mark.parametrize("defect", ["late_lease", "negative_repair", "false_replacement"])
def test_final_recovery_requires_cleanup_and_authoritative_replacements(defect):
    browser, native = sample()
    if defect == "late_lease":
        native["lease"]["active"] = True
    elif defect == "negative_repair":
        native["rows"][8]["repair_count"] = -5
    else:
        native["rows"][-1]["task_sequence"] = 11
        native["rows"].insert(
            -1,
            {
                "task_sequence": 10,
                "event_id": "e11",
                "event_type": "public_output",
                "output": "o2",
                "phase": "evidence",
                "refs": ["a"],
                "replaces": "invented",
            },
        )
    with pytest.raises(E2EError):
        validate_takeover(browser, native)


def test_global_run_budget_counts_the_interrupted_request_and_excludes_aux():
    browser, native = sample()
    native["budget"]["max_model_calls"] = 2
    browser["operator"]["before"]["budget"]["max_model_calls"] = 2
    with pytest.raises(E2EError, match="budget"):
        validate_takeover(browser, native)
    native["rows"][7]["purpose"] = "public_expression"
    native["rows"][8]["stage"] = "public_expression"
    validate_takeover(browser, native)


def test_prompt_preserves_read_only_business_and_no_fake_receipts():
    seed = {
        "scope": "actual_scratch_business_rows",
        "provider_or_receipt_injection": False,
        "seed_id": "a" * 16,
        "source_ids": ["b" * 32, "c" * 32],
        "event_ids": [f"{i:032x}" for i in range(48)],
        "event_count": 48,
        "per_source_count": 24,
    }
    prompt = takeover_prompt("ZEBRA_QA_SIMPLE_" + "a" * 32, seed)
    assert "events.search_history" in prompt and "不要修改" in prompt and "不要重复" in prompt


@pytest.mark.parametrize("mode,frozen", [("sidecar", "1"), ("host", "0"), ("", "1")])
def test_host_restart_requires_explicit_frozen_qa_authority(monkeypatch, mode, frozen):
    monkeypatch.setenv("ZEBRA_E2E_OPERATOR_MODE", mode)
    monkeypatch.setenv("ZEBRA_E2E_P1_FROZEN", frozen)
    with pytest.raises(E2EError, match="explicit_frozen"):
        host_worker_restart(SimpleNamespace(), "task", "run")


@pytest.mark.parametrize("defect", [None, "isolation", "source", "inactive"])
def test_host_restart_uses_only_validated_manifest_worker_never_browser_target(
    monkeypatch, tmp_path, defect
):
    import joint_worker_takeover as module
    import operator_sidecar

    target = "a" * 64
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"containers": {"worker": {"id": target}, "frontend": {"id": "b" * 64}}})
    )
    config = SimpleNamespace(isolation_manifest=str(manifest))
    monkeypatch.setenv("ZEBRA_E2E_OPERATOR_MODE", "host")
    monkeypatch.setenv("ZEBRA_E2E_P1_FROZEN", "1")

    def proof(_):
        if defect == "isolation":
            raise E2EError("scratch_isolation")
        return {"namespace_id": "qa"}

    monkeypatch.setattr(module, "joint_preflight", proof)
    monkeypatch.setattr(
        module,
        "native_source_identity",
        lambda _: {"worker": {"current_checkout_match": defect != "source"}},
    )
    monkeypatch.setattr(
        module, "native_execution", lambda *_: {"lease": {"active": defect != "inactive"}}
    )
    monkeypatch.setattr(module, "process_identity", lambda _: {"started_at": "old", "host_pid": 1})
    calls = []
    monkeypatch.setattr(
        operator_sidecar, "_restart_worker", lambda worker: calls.append(worker) or 204
    )
    if defect:
        with pytest.raises(E2EError):
            host_worker_restart(config, "task", "run")
        assert not calls
    else:
        assert host_worker_restart(config, "task", "run") == 204
        assert calls == [target]
        with pytest.raises(TypeError):
            host_worker_restart(config, "task", "run", container="b" * 64)
