"""The gate reports named facts, never deployment or universal non-commit proofs."""

import hashlib
import hmac
import json
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from agent_core.domain.runtime_gates import (
    CONTRACT_DIGEST,
    GateCommand,
    GateConflict,
    GateState,
    gate_observation,
)
from zebra_agent_config.bundle_settings import baseline_digest

from tests.test_bundle_assembly import settings


@pytest.mark.parametrize("action", ["drain", "open"])
def test_gate_transition_requires_original_revision(action):
    command = GateCommand(operation_id=uuid4(), action=action, expected_revision=3)
    state = GateState(revision=3, admission="open")
    assert state.apply(command).revision == 4
    with pytest.raises(GateConflict):
        GateState(revision=4, admission="open").apply(command)


@pytest.mark.parametrize(
    "input",
    [
        {"action": "assess", "expected_revision": 0},
        {"action": "drain", "expected_revision": True},
        {"action": "open", "expected_revision": -1},
        {"action": "resume", "expected_revision": 0},
        {"action": "drain", "expected_revision": 2**53 - 1},
    ],
)
def test_untrusted_intent_never_coerces(input):
    with pytest.raises(ValueError):
        GateCommand.model_validate({"operation_id": str(uuid4()), **input})


def test_quiescence_requires_closed_admission_and_all_named_facts():
    for mode, blockers in [
        ("open", {}),
        ("draining", {"unreleased_leases": 1}),
        ("draining", {"unsettled_effects": 1}),
        ("draining", {"projection_lag": 1}),
    ]:
        result = gate_observation(mode, blockers, [], source_complete=False)
        assert not result["executionQuiescent"]
        assert not result["safeToStop"] and not result["activationAuthorized"]
        assert result["processesStopped"] == "not_proven"
    assert gate_observation("draining", {}, [], source_complete=False)["executionQuiescent"]


def test_additive_gate_setting_preserves_exact_old_baseline_algorithm():
    original = settings()
    values = asdict(original)
    for key in [
        "model",
        "runtime_bundle_config",
        "bundle_management_config",
        "publication_management_config",
        "script_validation_config",
        "plugin_admission_config",
        "runtime_gate_config",
    ]:
        del values[key]
    raw = json.dumps(
        values, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode()
    historical = "sha256:" + hmac.new(bytes.fromhex("ab" * 32), raw, hashlib.sha256).hexdigest()
    assert baseline_digest(original, "ab" * 32) == historical
    assert (
        baseline_digest(replace(original, runtime_gate_config="/private/new-gates.json"), "ab" * 32)
        == historical
    )


def test_published_contract_digest_matches_embedded_runtime():
    from pathlib import Path

    from agent_core.domain.runtime_bundle_json import json_digest

    contract = json.loads(Path("docs/contracts/runtime-gates-v1/contract.json").read_text())
    assert json_digest(contract) == CONTRACT_DIGEST
