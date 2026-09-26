from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import cast

from agent_observability.live_eval_attempts import (
    attempt_from_envelope,
    digest_json,
    load_live_eval_attempts,
)
from agent_observability.live_eval_cases import LiveEvalCase, case_to_json, load_live_eval_cases


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one real Zebra live-eval attempt and independently verify it"
    )
    parser.add_argument("--cases", type=Path, default=Path("evals/live/cases"))
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--repetition", type=int, required=True)
    parser.add_argument("--runner-config", type=Path, required=True)
    parser.add_argument("--verifier-config", type=Path, required=True)
    parser.add_argument("--attempts", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    case = _find_case(load_live_eval_cases(args.cases), args.case_id)
    if args.repetition < 1 or args.repetition > case.repetitions:
        raise ValueError("repetition is outside the case contract")
    runner_config = _load_object(args.runner_config)
    verifier_config = _load_object(args.verifier_config)
    runner = _runner_identity(runner_config)
    if _string(verifier_config, "schema") != "zebra.live-eval-verifier-config.v1":
        raise ValueError("unsupported verifier config schema")
    if _string(verifier_config, "kind") != "external_postcondition":
        raise ValueError("live eval verifier must independently check postconditions")
    if _string(verifier_config, "verifier") != case.verifier:
        raise ValueError("verifier config does not match the case contract")

    request = {
        "schema": "zebra.live-eval-request.v1",
        "case": case_to_json(case),
        "repetition": args.repetition,
    }
    capture = _invoke(_argv(runner_config), request, args.timeout_seconds, "runner")
    verification = _invoke(
        _argv(verifier_config),
        {
            "schema": "zebra.live-eval-verification-request.v1",
            "request": request,
            "runner": runner,
            "capture": capture,
        },
        args.timeout_seconds,
        "verifier",
    )
    envelope = {
        "schema": "zebra.live-eval-attempt.v1",
        "case_id": case.case_id,
        "repetition": args.repetition,
        "runner": runner,
        "runner_sha256": digest_json(runner),
        "capture": capture,
        "capture_sha256": digest_json(capture),
        "verification": verification,
        "verification_sha256": digest_json(verification),
    }
    attempt = attempt_from_envelope(envelope)
    attempt.validate_case_contract(case)
    args.attempts.parent.mkdir(parents=True, exist_ok=True)
    existing = load_live_eval_attempts(args.attempts) if args.attempts.exists() else ()
    if any(
        item.case_id == attempt.case_id
        and item.repetition == attempt.repetition
        and item.evidence_tier == attempt.evidence_tier
        for item in existing
    ):
        raise ValueError("live eval attempt already exists for this case and evidence tier")
    with args.attempts.open("a", encoding="utf-8") as output:
        output.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())
    return 0


def _find_case(cases: tuple[LiveEvalCase, ...], case_id: str) -> LiveEvalCase:
    matches = [case for case in cases if case.case_id == case_id]
    if len(matches) != 1:
        raise ValueError(f"unknown live eval case: {case_id}")
    return matches[0]


def _load_object(path: Path) -> dict[object, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _runner_identity(config: dict[object, object]) -> dict[str, object]:
    if _string(config, "schema") != "zebra.live-eval-runner-config.v1":
        raise ValueError("unsupported runner config schema")
    kind = _choice(config, "kind", {"zebra_real_model", "real_dependency", "scripted"})
    provider = _optional_string(config, "provider")
    model = _optional_string(config, "model")
    if kind == "zebra_real_model" and (provider is None or model is None):
        raise ValueError("real-model runner config requires provider and model")
    if kind == "scripted" and (provider is not None or model is not None):
        raise ValueError("scripted runner config cannot claim a provider model")
    return {
        "kind": kind,
        "runner_id": _string(config, "runner_id"),
        "runtime": _string(config, "runtime"),
        "provider": provider,
        "model": model,
    }


def _invoke(
    argv: tuple[str, ...], request: dict[str, object], timeout: int, role: str
) -> dict[object, object]:
    completed = subprocess.run(
        argv,
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-1000:]
        raise RuntimeError(f"live eval {role} failed ({completed.returncode}): {detail}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"live eval {role} did not return one JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"live eval {role} output must be a JSON object")
    return cast(dict[object, object], value)


def _argv(config: dict[object, object]) -> tuple[str, ...]:
    raw = config.get("argv")
    if not isinstance(raw, list) or not raw:
        raise ValueError("live eval command argv must be a non-empty list")
    argv = tuple(item for item in raw if isinstance(item, str) and item)
    if len(argv) != len(raw):
        raise ValueError("live eval command argv entries must be non-blank strings")
    return argv


def _string(value: dict[object, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"live eval config field {key} must be a non-blank string")
    return raw


def _optional_string(value: dict[object, object], key: str) -> str | None:
    raw = value.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"live eval config field {key} must be a string or null")
    return raw


def _choice(value: dict[object, object], key: str, allowed: set[str]) -> str:
    result = _string(value, key)
    if result not in allowed:
        raise ValueError(f"live eval config field {key} is not supported")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
