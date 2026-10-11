"""Runner-boundary regressions, not real browser/provider/operator acceptance."""

from __future__ import annotations

import json
import stat
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import joint_operator_cases as module
import pytest
from support import E2EError
from test_joint_authority_cases import authority_sample
from test_joint_worker_takeover import sample

SEED = {
    "scope": "actual_scratch_business_rows",
    "provider_or_receipt_injection": False,
    "seed_id": "a" * 16,
    "source_ids": ["b" * 32, "c" * 32],
    "event_ids": [f"{i:032x}" for i in range(48)],
    "event_count": 48,
    "per_source_count": 24,
}
IDENTITY = {
    role: {"current_checkout_match": True, "hash": role}
    for role in ("worker", "zebra_api", "broker")
}


@pytest.fixture
def runner(monkeypatch, tmp_path):
    calls = []
    config = SimpleNamespace(
        bff_url="https://127.0.0.1:18443", session_cookie="private-cookie", timeout_seconds=5
    )
    environment = {"ZEBRA_E2E_P1_FROZEN": "1", "ZEBRA_E2E_COMMIT_VISIBILITY": "1"}
    monkeypatch.setattr(module, "joint_preflight", lambda _: calls.append("preflight"))
    monkeypatch.setattr(module, "native_source_identity", lambda _: deepcopy(IDENTITY))
    monkeypatch.setattr(module, "task_binding", lambda *_a, **_k: ("task", "opaque-thread"))
    return config, environment, tmp_path, calls


@pytest.mark.parametrize(
    "subcase", [None, "cancel", "approval", "scope_denial", "unknown_write_receipt"]
)
def test_wrapper_preserves_private_inputs_and_joins_independent_terminal(
    runner, monkeypatch, subcase
):
    config, environment, folder, calls = runner
    browser, native = sample() if subcase is None else authority_sample(subcase)
    browser["conversation_key"] = "conversation"
    if subcase is None:
        claim = deepcopy(native)
        claim.update(status="running", rows=native["rows"][:8])
        claim["lease"].update(active=True, checkpoint=5)
        browser["operator"]["after"] = claim
    captured = {}

    def launch(argv, **kwargs):
        calls.append("browser")
        inputs = json.loads(kwargs["input"])
        captured.update(inputs)
        private = Path(inputs["commit_inputs_path"])
        assert stat.S_IMODE(private.stat().st_mode) == 0o600
        assert json.loads(private.read_text()) == environment
        assert "private-cookie" not in " ".join(argv)
        assert kwargs["timeout"] == config.timeout_seconds + 60
        Path(inputs["evidence_dir"], inputs["case_id"].replace("_", "-") + ".json").write_text(
            json.dumps(browser)
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", launch)
    monkeypatch.setattr(module, "native_execution", lambda *_a: calls.append("terminal") or native)
    monkeypatch.setattr(module, "native_authority", lambda *_a: calls.append("terminal") or native)
    if subcase is None:
        result = module.run_takeover_case(config, environment, folder, seed=SEED)
        assert result["browser"]["operator"]["after_claim"] == claim
        assert result["browser"]["operator"]["after"] == native
        assert browser["operator"]["after"] == claim  # Never overwrite raw operator evidence.
        assert captured["operator_script"].endswith("joint_worker_takeover.py")
    else:
        result = module.run_authority_case(config, environment, folder, subcase=subcase, seed=SEED)
        assert captured["authority_subcase"] == subcase
        assert captured["operator_script"].endswith("joint_authority_cases.py")
        assert captured["authority_observer"].endswith("browser_authority_observer.mjs")
        if subcase == "unknown_write_receipt":
            assert captured["source_id"] == SEED["source_ids"][0]
    assert calls == ["preflight", "browser", "terminal"]
    assert not Path(captured["commit_inputs_path"]).exists()
    assert result["native"] == native
    assert result["healthy_samples"] == 0 and result["full_goal_passed"] is False


@pytest.mark.parametrize("defect", ["not_frozen", "missing_role", "stale_source", "invalid_seed"])
def test_invalid_inputs_or_source_never_launch_browser(runner, monkeypatch, defect):
    config, environment, folder, calls = runner
    seed = deepcopy(SEED)
    identity = deepcopy(IDENTITY)
    if defect == "not_frozen":
        environment["ZEBRA_E2E_P1_FROZEN"] = "0"
    elif defect == "missing_role":
        identity.pop("broker")
    elif defect == "stale_source":
        identity["worker"]["current_checkout_match"] = False
    else:
        seed["provider_or_receipt_injection"] = True
    monkeypatch.setattr(module, "native_source_identity", lambda _: identity)
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: pytest.fail("unsafe browser"))
    with pytest.raises(E2EError):
        module.run_takeover_case(config, environment, folder, seed=seed)


@pytest.mark.parametrize("defect", ["prefix", "run", "anchor", "segment", "fence", "healthy"])
def test_claim_is_not_relabelled_as_success_when_identity_or_prefix_changes(defect):
    browser, native = sample()
    claim = deepcopy(native)
    claim.update(status="running", rows=deepcopy(native["rows"][:8]))
    claim["lease"].update(active=True, checkpoint=5)
    browser["operator"]["after"] = claim
    if defect == "prefix":
        claim["rows"][0]["event_id"] = "changed"
    elif defect in {"run", "anchor", "segment"}:
        claim[{"run": "run_id", "anchor": "anchor_id", "segment": "segment"}[defect]] = "other"
    elif defect == "fence":
        claim["lease"]["token"] = native["lease"]["token"] + 1
    else:
        browser["healthy_samples"] = 1
    with pytest.raises(E2EError):
        module.observe_takeover_terminal(browser, native)


def test_source_refresh_during_browser_invalidates_slice(runner, monkeypatch):
    config, environment, folder, _ = runner
    browser, native = sample()
    browser["conversation_key"] = "conversation"
    identities = iter([deepcopy(IDENTITY), {**IDENTITY, "new_build": {}}])
    monkeypatch.setattr(module, "native_source_identity", lambda _: next(identities))

    def launch(_argv, **kwargs):
        inputs = json.loads(kwargs["input"])
        Path(inputs["evidence_dir"], "worker-takeover.json").write_text(json.dumps(browser))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", launch)
    monkeypatch.setattr(module, "native_execution", lambda *_a: native)
    with pytest.raises(E2EError, match="source_changed"):
        module.run_takeover_case(config, environment, folder, seed=SEED)
