"""Explicit opt-in actual Host/Worker/PG/SSE matrix, never a FakeProvider test."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from joint_concurrency_cases import HISTORIES, OBSERVERS, run_concurrency_case
from run_acceptance import REQUIRED_ENV
from support import E2EError, load_config


@pytest.mark.parametrize("history", HISTORIES)
@pytest.mark.parametrize("observers", OBSERVERS)
def test_actual_bounded_concurrency_matrix(history, observers):
    """Main supplies existing protected inputs and a real completed scratch conversation."""
    inputs_path = os.environ.get("ZEBRA_JOINT_CONCURRENCY_INPUTS")
    conversation = os.environ.get("ZEBRA_JOINT_CONCURRENCY_CONVERSATION")
    output = os.environ.get("ZEBRA_JOINT_CONCURRENCY_OUTPUT")
    if not inputs_path or not conversation or not output:
        pytest.skip("explicit isolated joint inputs/conversation/output required")
    path = Path(inputs_path)
    if path.stat().st_size > 32_768 or path.stat().st_mode & 0o077:
        pytest.fail("joint inputs must be bounded and private", pytrace=False)
    inputs = json.loads(path.read_text())
    for name in ("TRENCH_E2E_BUSINESS_SNAPSHOT_URL", "ZEBRA_E2E_WORKER_RESTART_URL"):
        inputs.setdefault(name, inputs["TRENCH_E2E_BFF_URL"])
    inputs.setdefault("TRENCH_E2E_EVENT_ID", "unused_in_concurrency")
    try:
        evidence = asyncio.run(
            run_concurrency_case(
                load_config(inputs, REQUIRED_ENV),
                conversation,
                history=history,
                observers=observers,
            )
        )
    except BaseExceptionGroup as exc:
        leaves = list(exc.exceptions)
        codes = []
        while leaves:
            leaf = leaves.pop()
            if isinstance(leaf, BaseExceptionGroup):
                leaves.extend(leaf.exceptions)
            else:
                codes.append(leaf.code if isinstance(leaf, E2EError) else type(leaf).__name__)
        pytest.fail("bounded_concurrency_failed:" + ",".join(sorted(set(codes))), pytrace=False)
    except Exception as exc:
        code = exc.code if isinstance(exc, E2EError) else type(exc).__name__
        pytest.fail("bounded_concurrency_failed:" + code, pytrace=False)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"history-{history}-observers-{observers}.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
