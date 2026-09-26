from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

try:
    from live_eval_fixture import workspace_digest
except ModuleNotFoundError:  # imported as scripts.live_eval_verifier in tests
    from scripts.live_eval_fixture import workspace_digest


def main() -> int:
    envelope = json.load(sys.stdin)
    request = envelope["request"]
    case = request["case"]
    capture = envelope["capture"]
    workspace = Path(capture["workspace_path"]).resolve()
    database = Path(capture["database_path"]).resolve()
    manifest = json.loads((workspace / "fixture-manifest.json").read_text(encoding="utf-8"))
    event_evidence = _attest_events(database, capture)
    checks = _verify_case(
        str(case["category"]), workspace, str(capture["assistant_message"]), manifest
    )
    passed = all(checks)
    evidence = list(case["postcondition"]["evidence"])
    result = {
        "verifier": case["postcondition"]["verifier"],
        "assertions": [
            {"assertion": assertion, "passed": passed, "evidence": evidence}
            for assertion in case["postcondition"]["assertions"]
        ],
        "runner_attested": True,
        "attestation_evidence": event_evidence,
        "citation_supported": passed if case["category"] in {"answer", "research"} else None,
        "recovery_succeeded": passed if case["category"] == "memory_recovery" else None,
        "independent_checks": checks,
        "final_workspace_sha256": workspace_digest(workspace),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _attest_events(database: Path, capture: dict[str, object]) -> list[str]:
    if not database.is_file():
        raise ValueError("authoritative event database is missing")
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT event_type, payload FROM session_events WHERE session_id = ? ORDER BY sequence",
            (capture["session_id"],),
        ).fetchall()
    finally:
        connection.close()
    model_ids = [
        str(json.loads(payload)["model_call_id"])
        for event_type, payload in rows
        if event_type == "model_response_received"
    ]
    if model_ids != capture["model_call_ids"]:
        raise ValueError("capture model calls do not match authoritative events")
    return [f"zebra:model-call:{call_id}" for call_id in model_ids]


def _verify_case(
    category: str, workspace: Path, answer: str, manifest: dict[str, object]
) -> list[bool]:
    terms = [str(value) for value in manifest["required_terms"]]
    answer_term_check = _contains_terms(answer, terms)
    if category in {"answer", "research"}:
        citation_check = _has_existing_citation(workspace, answer)
        return [bool(answer.strip()), answer_term_check, citation_check]
    if category == "code":
        tests = subprocess.run(
            [sys.executable, "-m", "unittest", "-v"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        return [
            tests.returncode == 0,
            (workspace / "unrelated.txt").read_text() == "preserve-me\n",
            answer_term_check,
        ]
    if category == "file":
        target = Path(str(manifest["validation"][0]))
        output = workspace / target
        output_text = _read_text(output)
        return [
            output.is_file(),
            output.stat().st_size > 20 if output.is_file() else False,
            _contains_terms(output_text, terms),
        ]
    if category == "operation":
        state_text = (workspace / "state.json").read_text()
        state = json.loads(state_text)
        state_terms = _contains_terms(f"{state_text}\n{answer}", terms)
        return [state.get("writes") == 1, state_terms, bool(answer.strip())]
    if category == "memory_recovery":
        target = workspace / str(manifest["validation"][0])
        if not target.is_file():
            return [False, False, False]
        target_text = target.read_text()
        try:
            payload = json.loads(target_text)
        except json.JSONDecodeError:
            return [False, False, False]
        scoped = payload.get("selected_scope") == "user-7" or payload.get("replayed") is False
        return [scoped, payload.get("writes", 1) == 1, _contains_terms(target_text, terms)]
    raise ValueError(f"unsupported category: {category}")


def _contains_terms(value: str, terms: list[str]) -> bool:
    normalized = value.casefold()
    return all(term.casefold() in normalized for term in terms)


def _has_existing_citation(workspace: Path, answer: str) -> bool:
    paths = [
        path
        for directory in ("evidence", "sources")
        for path in (workspace / directory).rglob("*")
        if path.is_file()
    ]
    return any(
        str(path.relative_to(workspace)) in answer
        or (sum(item.name == path.name for item in paths) == 1 and path.name in answer)
        for path in paths
    )


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
