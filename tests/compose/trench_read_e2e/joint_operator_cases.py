"""Real browser/operator launch boundaries; guards alone never count as live acceptance."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from isolation import joint_preflight
from joint_acceptance import native_source_identity
from joint_authority_cases import authority_prompt, native_authority, validate_authority
from joint_worker_takeover import native_execution, takeover_prompt, validate_takeover
from support import Config, E2EError, task_binding


def observe_takeover_terminal(
    evidence: Mapping[str, Any], native: Mapping[str, Any]
) -> dict[str, Any]:
    """Retain the operator's actual new claim and independently join its terminal prefix."""
    op = evidence.get("operator", {})
    claim = op.get("after", {})
    lease, final_lease = claim.get("lease", {}), native.get("lease", {})
    rows = claim.get("rows", [])
    if (
        not rows
        or any(claim.get(k) != native.get(k) for k in ("task_id", "run_id", "anchor_id", "segment"))
        or native.get("rows", [])[: len(rows)] != rows
        or lease.get("epoch") != final_lease.get("epoch")
        or type(lease.get("token")) is not int
        or type(final_lease.get("token")) is not int
        or final_lease["token"] < lease["token"]
        or type(lease.get("checkpoint")) is not int
        or type(final_lease.get("checkpoint")) is not int
        or final_lease["checkpoint"] < lease["checkpoint"]
    ):
        raise E2EError("takeover_claim_terminal_prefix_changed")
    joined = {
        **evidence,
        "healthy_samples": evidence.get("healthy_samples", 0),
        "operator": {**op, "after_claim": claim, "after": native},
    }
    validate_takeover(joined, native)
    return joined


def _run_case(
    config: Config,
    environment: Mapping[str, str],
    evidence_dir: Path,
    *,
    case_id: str,
    subcase: str | None,
    seed: Mapping[str, Any],
) -> dict[str, Any]:
    if environment.get("ZEBRA_E2E_P1_FROZEN") != "1":
        raise E2EError("operator_latest_build_freeze_required")
    marker = "ZEBRA_QA_SIMPLE_" + uuid4().hex
    prompt = (
        takeover_prompt(marker, seed)
        if case_id == "worker_takeover"
        else authority_prompt(subcase or "", marker, seed)
    )
    joint_preflight(config)
    identity = native_source_identity(config)
    for role in ("worker", "zebra_api", "broker"):
        deployed = identity.get(role)
        if not isinstance(deployed, Mapping) or deployed.get("current_checkout_match") is not True:
            raise E2EError("operator_latest_source_not_deployed")
    root = Path(__file__).resolve().parent
    script = root.parents[2].parent / "Trench/toc-frontend/scripts/strategy-joint-acceptance.mjs"
    inputs: dict[str, Any] = {
        "case_id": case_id,
        "prompt": prompt,
        "expected": marker,
        "operator_script": str(
            root
            / (
                "joint_worker_takeover.py"
                if case_id == "worker_takeover"
                else "joint_authority_cases.py"
            )
        ),
        "base_url": config.bff_url,
        "cookie": config.session_cookie,
        "timeout_ms": config.timeout_seconds * 1000,
        "python": sys.executable,
        "guard_script": str(root / "run_acceptance.py"),
        "cleanup_script": str(root / "terminal_probe.py"),
        "evidence_dir": str(evidence_dir.resolve()),
        "tls_spki": environment.get("ZEBRA_E2E_TLS_SPKI", ""),
    }
    if case_id == "authority":
        inputs.update(
            authority_subcase=subcase,
            authority_observer=str(root / "browser_authority_observer.mjs"),
        )
        if subcase == "unknown_write_receipt":
            inputs["source_id"] = seed["source_ids"][0]
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as private_inputs:
        if environment.get("ZEBRA_E2E_COMMIT_VISIBILITY") == "1":
            json.dump(dict(environment), private_inputs)
            private_inputs.flush()
            inputs["commit_inputs_path"] = private_inputs.name
        completed = subprocess.run(
            [environment.get("ZEBRA_E2E_NODE", "node"), str(script)],
            cwd=script.parent.parent,
            env=dict(environment),
            input=json.dumps(inputs),
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds + 60,
            check=False,
        )
    if completed.returncode != 0:
        raise E2EError("operator_real_browser_executor_failed")
    path = evidence_dir / (case_id.replace("_", "-") + ".json")
    if path.stat().st_size > 1_048_576:
        raise E2EError("operator_browser_evidence_limit")
    browser = json.loads(path.read_text())
    task, _ = task_binding(config, conversation_key=browser["conversation_key"], simple_slice=True)
    deadline = time.monotonic() + 2
    if case_id == "worker_takeover":
        native = native_execution(config, task, browser["run_id"], deadline)
        browser = observe_takeover_terminal(browser, native)
    else:
        native = native_authority(config, task, browser["run_id"], deadline)
        browser = {**browser, "healthy_samples": browser.get("healthy_samples", 0)}
        if browser.get("authority_subcase") != subcase:
            raise E2EError("authority_browser_subcase_changed")
        validate_authority(browser, native)
    if native_source_identity(config) != identity:
        raise E2EError("operator_source_changed_during_run")
    return {
        "case_id": case_id,
        "authority_subcase": subcase,
        "status": "slice_passed",
        "source_identity": identity,
        "native": native,
        "browser": browser,
        "healthy_samples": 0,
        "full_goal_passed": False,
    }


def run_takeover_case(
    config: Config, environment: Mapping[str, str], evidence_dir: Path, *, seed: Mapping[str, Any]
) -> dict[str, Any]:
    return _run_case(
        config, environment, evidence_dir, case_id="worker_takeover", subcase=None, seed=seed
    )


def run_authority_case(
    config: Config,
    environment: Mapping[str, str],
    evidence_dir: Path,
    *,
    subcase: str,
    seed: Mapping[str, Any],
) -> dict[str, Any]:
    return _run_case(
        config, environment, evidence_dir, case_id="authority", subcase=subcase, seed=seed
    )
