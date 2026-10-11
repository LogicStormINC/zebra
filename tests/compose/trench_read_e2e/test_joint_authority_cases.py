"""Authority evidence rejection checks, never counted as native/live acceptance."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from joint_authority_cases import authority_prompt, validate_authority, validate_authority_matrix
from support import E2EError
from test_joint_worker_takeover import sample


def authority_sample(subcase):
    browser, native = sample()
    browser.update(case_id="authority", authority_subcase=subcase)
    op = {
        "schema_version": "zebra.joint-authority.v1",
        "scope": "actual_scratch_authority_http_and_native_pg",
        "provider_or_receipt_injection": False,
        "task_id": native["task_id"],
        "run_id": native["run_id"],
        "subcase": subcase,
        "native": native,
        "action_accepted": True,
    }
    browser["operator"] = op
    native["lease"]["released"] = True
    native["worker"] = {
        "coverage_complete": True,
        **dict.fromkeys(
            (
                "execution_threads",
                "model_threads",
                "public_wait_timers",
                "text_flush_timers",
                "lease_heartbeat_threads",
            ),
            0,
        ),
    }
    if subcase in {"cancel", "approval"}:
        native["rows"].pop()  # Actual rejected/cancelled Runs need no fake final answer.
        browser["final_count"] = 0
        browser["terminal_observed_to_cleanup_ms"] = 500
        browser["cleanup"]["browser_closed"] = True
        if subcase == "cancel":
            native["status"] = "cancelled"
            native["rows"].append(
                {"task_sequence": 10, "event_id": "cancel", "event_type": "session_cancelled"}
            )
            op["armed_sequence"] = 9
            op["worker_before"] = {
                "coverage_complete": True,
                "execution_threads": 1,
                "model_threads": 1,
            }
            browser["frames"] = [{"cursor": 1, "type": "cancelled"}]
        else:
            native["status"] = "failed"
            native["rows"].extend(
                [
                    {
                        "task_sequence": 10,
                        "event_id": "app",
                        "event_type": "approval_requested",
                        "call": "blocked-call",
                        "fingerprint": "f" * 64,
                        "tool_name": "command.run",
                    },
                    {
                        "task_sequence": 11,
                        "event_id": "reject",
                        "event_type": "approval_rejected",
                        "call": "blocked-call",
                        "fingerprint": "f" * 64,
                    },
                ]
            )
            browser["frames"] = [
                {
                    "cursor": 1,
                    "type": "approval_request",
                    "tool_call_id": "blocked-call",
                    "call_fingerprint": "f" * 64,
                }
            ]
            browser["approval_visibility"] = {
                "tool_call_id": "blocked-call",
                "call_fingerprint": "f" * 64,
                "before_decision": True,
                "screenshot": "approval.png",
            }
            op["target_call_id"] = "blocked-call"
            op["decision"] = "reject"
    elif subcase == "scope_denial":
        op["http_statuses"] = [404, 200, 401]
        op["replay_counts"] = [0, 0, 1, 1]
        op["target_run_changed"] = True
        op["same_grant_reused"] = True
    else:
        native["rows"][-1]["task_sequence"] = 13
        native["rows"][-1:-1] = [
            {
                "task_sequence": 10,
                "event_id": "write-start",
                "event_type": "tool_execution_started",
                "call": "write",
                "tool_name": "sources.pause",
            },
            {
                "task_sequence": 11,
                "event_id": "write-fail",
                "event_type": "tool_execution_failed",
                "call": "write",
                "tool_name": "sources.pause",
                "reason": "host_effect_unconfirmed",
                "transport": "returned",
                "outcome": "unknown",
            },
            {
                "task_sequence": 12,
                "event_id": "recovery",
                "event_type": "public_output",
                "output": "o2",
                "phase": "recovery",
                "refs": ["write"],
                "content": "Outcome unconfirmed; do not retry.",
            },
        ]
        op.update(
            target_call_id="write",
            source_before="active",
            source_after="paused",
            source_id="a" * 16 + "0" * 16,
        )
        native["effects"] = [
            {
                "intent_event_id": "write-start",
                "status": "uncertain",
                "attempt": 1,
                "target_hash": sha256(
                    json.dumps(
                        {"source_id": op["source_id"]},
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest(),
            }
        ]
        browser["fault_visibility"] = [
            {
                "output_id": "o2",
                "before_terminal": True,
                "before_final_receipt": True,
                "content_sha256": sha256(b"Outcome unconfirmed; do not retry.").hexdigest(),
            }
        ]
    return browser, native


@pytest.mark.parametrize("subcase", ["cancel", "approval", "scope_denial", "unknown_write_receipt"])
def test_actual_subcase_contract_without_substituting_final_for_cancel(subcase):
    browser, native = authority_sample(subcase)
    validate_authority(browser, native)


@pytest.mark.parametrize(
    "subcase,defect",
    [
        ("cancel", "no_execution"),
        ("cancel", "late_public"),
        ("cancel", "fake_final"),
        ("approval", "no_request"),
        ("approval", "wrong_fingerprint"),
        ("approval", "early_dispatch"),
        ("approval", "no_dom"),
        ("scope_denial", "availability"),
        ("scope_denial", "consumed_denial"),
        ("scope_denial", "no_replay"),
        ("scope_denial", "different_grant"),
        ("unknown_write_receipt", "fake_applied"),
        ("unknown_write_receipt", "no_dispatch"),
        ("unknown_write_receipt", "no_write"),
        ("unknown_write_receipt", "retry"),
        ("unknown_write_receipt", "no_public"),
        ("unknown_write_receipt", "missing_effect"),
        ("unknown_write_receipt", "wrong_source"),
    ],
)
def test_flags_or_http_200_cannot_replace_authoritative_evidence(subcase, defect):
    browser, native = authority_sample(subcase)
    op = browser["operator"]
    if defect == "no_execution":
        op["worker_before"]["model_threads"] = 0
    elif defect == "late_public":
        native["rows"].append(
            {"task_sequence": 11, "event_id": "late", "event_type": "public_output"}
        )
    elif defect == "fake_final":
        native["rows"][-1]["event_type"] = "answer_committed"
    elif defect == "no_request":
        native["rows"][-2]["event_type"] = "policy_decision_recorded"
    elif defect == "wrong_fingerprint":
        native["rows"][-1]["fingerprint"] = "b" * 64
    elif defect == "early_dispatch":
        native["rows"].append(
            {
                "task_sequence": 12,
                "event_id": "dispatch",
                "event_type": "tool_execution_started",
                "call": "blocked-call",
            }
        )
    elif defect == "no_dom":
        browser["approval_visibility"]["before_decision"] = False
    elif defect == "availability":
        op["http_statuses"][0] = 503
    elif defect == "consumed_denial":
        op["replay_counts"][1] = 1
    elif defect == "no_replay":
        op["http_statuses"][2] = 200
    elif defect == "different_grant":
        op["same_grant_reused"] = False
    elif defect == "fake_applied":
        native["rows"][-3]["outcome"] = "applied"
    elif defect == "no_dispatch":
        native["rows"][-4]["event_type"] = "tool_call_proposed"
    elif defect == "no_write":
        op["source_after"] = "active"
    elif defect == "retry":
        native["rows"].append(
            {
                "task_sequence": 14,
                "event_id": "retry",
                "event_type": "tool_execution_started",
                "tool_name": "sources.pause",
                "call": "retry",
            }
        )
    elif defect == "no_public":
        browser["fault_visibility"] = []
    elif defect == "wrong_source":
        native["effects"][0]["target_hash"] = "0" * 64
    else:
        native["effects"] = []
    with pytest.raises((E2EError, ValueError)):
        validate_authority(browser, native)


@pytest.mark.parametrize("subcase", ["cancel", "approval", "scope_denial", "unknown_write_receipt"])
def test_identity_and_terminal_cleanup_are_required_for_every_subcase(subcase):
    browser, native = authority_sample(subcase)
    for field in ("run_id", "task_id"):
        modified = deepcopy(browser)
        modified["operator"][field] = "substituted"
        with pytest.raises(E2EError):
            validate_authority(modified, native)
    native["worker"]["text_flush_timers"] = 1
    with pytest.raises(E2EError):
        validate_authority(browser, native)


def test_matrix_requires_all_four_native_subcases_and_never_counts_healthy_samples():
    cases = {
        s: {"browser": b, "native": n}
        for s in ("cancel", "approval", "scope_denial", "unknown_write_receipt")
        for b, n in [authority_sample(s)]
    }
    validate_authority_matrix(cases)
    cases.pop("approval")
    with pytest.raises(E2EError):
        validate_authority_matrix(cases)


def test_prompts_use_existing_actual_tools_not_synthetic_approval_or_receipts():
    seed = {
        "scope": "actual_scratch_business_rows",
        "provider_or_receipt_injection": False,
        "seed_id": "a" * 16,
        "source_ids": ["a" * 16 + f"{i:016x}" for i in range(2)],
        "event_ids": [f"{i:032x}" for i in range(48)],
        "event_count": 48,
        "per_source_count": 24,
    }
    marker = "ZEBRA_QA_SIMPLE_" + "b" * 32
    assert "sources.pause" in authority_prompt("unknown_write_receipt", marker, seed)
    assert "command.run" in authority_prompt("approval", marker, seed)
    with pytest.raises(E2EError):
        authority_prompt("fake", marker, seed)
