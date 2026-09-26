# ruff: noqa: E501 -- fixture source strings remain literal and independently hashable.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

try:
    from live_eval_fixture_mutations import MUTATION_CASES
except ModuleNotFoundError:  # imported as scripts.live_eval_fixture in tests
    from scripts.live_eval_fixture_mutations import MUTATION_CASES

PILOT_CASE_IDS = (
    "answer-authority-boundary",
    "answer-incident-timeline",
    "research-current-official",
    "research-vendor-claim",
    "code-python-shared-root",
    "code-api-auth",
    "file-markdown-report",
    "file-document-extract",
    "operation-idempotent-write",
    "operation-partial-reconcile",
    "memory-recovery-cross-session-preference",
    "memory-recovery-postwrite-reconcile",
)


@dataclass(frozen=True)
class FixtureSpec:
    files: dict[str, str]
    instructions: str
    required_terms: tuple[str, ...]
    validation: tuple[str, ...]


def materialize(case: dict[str, object], workspace: Path) -> FixtureSpec:
    case_id = str(case["case_id"])
    spec = _spec(case_id)
    for name, content in spec.files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    manifest = {
        "case_id": case_id,
        "fixture_id": dict(case["fixture"])["fixture_id"],
        "required_terms": list(spec.required_terms),
        "validation": list(spec.validation),
    }
    (workspace / "fixture-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return spec


def workspace_digest(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in workspace.rglob("*") if item.is_file()):
        if path.name == "session.sqlite" or {"__pycache__", ".git"}.intersection(path.parts):
            continue
        digest.update(str(path.relative_to(workspace)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _spec(case_id: str) -> FixtureSpec:
    if case_id in SPECS:
        return SPECS[case_id]
    if case_id in EVIDENCE_CASES:
        directory, body, terms = EVIDENCE_CASES[case_id]
        path = f"{directory}/{case_id}.md"
        return FixtureSpec(
            files={path: body},
            instructions=(
                f"Use only {path}. Answer the requested case directly, cite {path}, "
                "and explicitly separate observed facts, inference, and unresolved uncertainty."
            ),
            required_terms=terms,
            validation=("answer", "citations"),
        )
    if case_id in MUTATION_CASES:
        spec = MUTATION_CASES[case_id]
        return FixtureSpec(*spec)
    raise ValueError(f"live-eval fixture is not materialized: {case_id}")


EVIDENCE_CASES = {
    "answer-failure-diagnosis": (
        "evidence",
        "# Worker failure\nObserved: task accepted at 10:00:01; provider returned 429 at 10:00:04; wrapper emitted model execution failed at 10:00:05. No tool started. Retry-After was 30 seconds.\n",
        ("429", "model execution failed", "30 seconds", "inference"),
    ),
    "answer-permission-explanation": (
        "evidence",
        "# Policy decision\nObserved request: command.run rm -rf /tmp/export. Policy profile: read_only. Decision: deny workspace mutation. Approval state: none requested. Least-privilege action: inspect with files.list and request scoped approval only if deletion remains necessary.\n",
        ("read_only", "deny", "files.list", "scoped approval"),
    ),
    "answer-architecture-tradeoff": (
        "evidence",
        "# Storage comparison\nPostgreSQL provides transactions and tenant-scoped authority. Redis provides low-latency ephemeral caching but may be flushed. Requirement: confirmed user memory must survive cache loss.\n",
        ("PostgreSQL", "Redis", "survive cache loss", "inference"),
    ),
    "answer-log-evidence": (
        "evidence",
        "# Partial log\n12:01 API committed task t-7. 12:02 worker lease acquired. 12:04 stream idle timeout. There is no provider response or worker-exit record in this excerpt.\n",
        ("t-7", "stream idle timeout", "no provider response", "uncertainty"),
    ),
    "answer-migration-risk": (
        "evidence",
        "# Migration plan\nMigration 58 adds nullable result_digest, then backfills in batches of 500. Old workers ignore the column. The proposal makes it NOT NULL before the backfill completes.\n",
        ("result_digest", "500", "NOT NULL", "backfill"),
    ),
    "answer-config-precedence": (
        "evidence",
        "# Config resolution\nDocumented precedence: explicit CLI flag, environment, config file, default. Inputs: CLI has no timeout; environment timeout=45; file timeout=60; default=30.\n",
        ("environment", "45", "config file", "default"),
    ),
    "answer-data-authority": (
        "evidence",
        "# Read mismatch\nPostgreSQL task row revision=18 status=completed. Redis projection revision=16 status=running. Projection policy says PostgreSQL is authoritative and stale cache entries must be invalidated.\n",
        ("revision=18", "revision=16", "PostgreSQL", "invalidate"),
    ),
    "answer-user-recovery": (
        "evidence",
        "# Recovery state\nTask q-9 is durable and still queued. Transport disconnected after event 24. No external write started. Supported action: reconnect from cursor 24; do not create a replacement task.\n",
        ("q-9", "cursor 24", "reconnect", "do not create"),
    ),
    "research-conflicting-sources": (
        "sources",
        "# Conflict record\nPrimary release note (2026-09-18): API v1 retires 2026-12-31. Community post (2026-09-19): claims v1 already stopped. Status snapshot (2026-09-20): v1 returns 200 and deprecation headers.\n",
        ("2026-12-31", "community", "200", "deprecation"),
    ),
    "research-api-change": (
        "sources",
        "# API notice\nOfficial notice dated 2026-09-10: field retryLimit is deprecated, replacement retryPolicy, removal version 3.0. Current fixture version is 2.4.\n",
        ("retryLimit", "retryPolicy", "3.0", "2.4"),
    ),
    "research-security-advisory": (
        "sources",
        "# Advisory ZSA-2026-04\nPublished 2026-09-12. Affects 1.4.0 through 1.4.3 when archive extraction is enabled. Fixed in 1.4.4. Target inventory: 1.4.2 with extraction disabled.\n",
        ("ZSA-2026-04", "1.4.2", "extraction disabled", "1.4.4"),
    ),
    "research-library-compatibility": (
        "sources",
        "# Compatibility matrix\nReact 18 and 19 are supported. Next 15 requires package exports and use client on interactive entries. Node runtime range is 22.18 or newer below 25.\n",
        ("React 18", "React 19", "Next 15", "22.18"),
    ),
    "research-protocol-standard": (
        "sources",
        "# Protocol requirement\nProtocol v2 requires monotonically increasing event sequence, resumable cursor, and idempotency key on external writes. A 200 response alone is not completion evidence.\n",
        ("monotonically increasing", "resumable cursor", "idempotency key", "200"),
    ),
    "research-policy-current": (
        "sources",
        "# Service policy\nEffective 2026-09-01: retention is 30 days for standard and 365 days for audit records. Deletion requests suppress recall immediately and purge payloads within 24 hours.\n",
        ("2026-09-01", "30 days", "365 days", "24 hours"),
    ),
    "research-benchmark-reproduction": (
        "sources",
        "# Benchmark inputs\nVendor result used 100 identical warm prompts, one tenant, no tools. Target comparison requires 500 mixed prompts, 20 tenants, cold and warm lanes, fixed model settings, and three repetitions.\n",
        ("100 identical", "500 mixed", "20 tenants", "three repetitions"),
    ),
    "research-release-regression": (
        "sources",
        "# Regression evidence\nVersion 2.3 median latency 420ms over 100 requests. Version 2.4 median 690ms over 100 requests. The only recorded change is compression enabled; no controlled disable-compression run exists.\n",
        ("420ms", "690ms", "compression", "no controlled"),
    ),
}


SPECS = {
    "answer-authority-boundary": FixtureSpec(
        files={
            "evidence/architecture.md": "# Authority record\nSessions: PostgreSQL. Artifacts: MinIO payload with PostgreSQL metadata. Governed memory: PostgreSQL. Redis: live-event transport only.\n"
        },
        instructions="Read evidence/architecture.md. Answer the authority question with file citations and separate facts from inference.",
        required_terms=("PostgreSQL", "MinIO", "Redis", "inference"),
        validation=("answer",),
    ),
    "answer-incident-timeline": FixtureSpec(
        files={
            "evidence/events.log": "2026-09-20T10:00:03Z worker received job\n2026-09-20T10:00:01Z API committed command\n2026-09-20T10:00:05Z provider timed out\n2026-09-20T10:00:04Z model request started\n"
        },
        instructions="Read evidence/events.log. Reconstruct observed timestamp order and separately label any inferred causal order.",
        required_terms=("10:00:01", "10:00:03", "10:00:04", "10:00:05", "inferred"),
        validation=("answer",),
    ),
    "research-current-official": FixtureSpec(
        files={
            "sources/official-release.md": "# Official Zebra dependency release note\nPublished: 2026-09-01\nVersion 2.0 removes legacy retryLimit and supports retryPolicy. Migration deadline: 2026-12-01.\n",
            "sources/community.md": "# Community note\nPublished: 2026-08-01\nClaims retryLimit remains supported indefinitely.\n",
        },
        instructions="Use only files under sources/. Treat official-release.md as primary. Produce a dated summary with claim-level file citations and resolve the conflict.",
        required_terms=("2026-09-01", "retryPolicy", "2026-12-01", "official-release.md"),
        validation=("answer", "citations"),
    ),
    "research-vendor-claim": FixtureSpec(
        files={
            "sources/vendor.md": "# Vendor benchmark\nPublished: 2026-08-15\nClaim: 99% cache hit rate on 100 identical prompts after warmup, 1 tenant, no tool schemas.\n",
            "sources/workload.md": "# Target workload\nPublished: 2026-09-20\nThe target has 500 mixed prompts, 20 tenants, changing tool schemas, and cold starts. No reproduction has been run.\n",
        },
        instructions="Assess the vendor claim using only sources/. Cite each material claim, state applicability limits, and do not report an unrun result.",
        required_terms=("99%", "100 identical", "20 tenants", "not", "vendor.md"),
        validation=("answer", "citations"),
    ),
    "code-python-shared-root": FixtureSpec(
        files={
            "identity.py": "def tenant_for(requested: str, authenticated: str) -> str:\n    return requested\n\ndef api_tenant(requested: str, authenticated: str) -> str:\n    return tenant_for(requested, authenticated)\n\ndef worker_tenant(requested: str, authenticated: str) -> str:\n    return tenant_for(requested, authenticated)\n",
            "test_identity.py": "import unittest\nfrom identity import api_tenant, worker_tenant\n\nclass TestTenant(unittest.TestCase):\n    def test_all_callers_use_authenticated_tenant(self):\n        self.assertEqual(api_tenant('attacker', 'tenant-a'), 'tenant-a')\n        self.assertEqual(worker_tenant('attacker', 'tenant-a'), 'tenant-a')\n\nif __name__ == '__main__': unittest.main()\n",
            "unrelated.txt": "preserve-me\n",
        },
        instructions="Trace both callers, fix the shared root cause in identity.py, preserve unrelated.txt, and run python -m unittest -v.",
        required_terms=("tenant_for", "unittest"),
        validation=("python-tests", "preserve-unrelated"),
    ),
    "code-api-auth": FixtureSpec(
        files={
            "auth.py": "def authorize(token_tenant: str, path_tenant: str) -> bool:\n    return bool(token_tenant and path_tenant)\n",
            "test_auth.py": "import unittest\nfrom auth import authorize\n\nclass TestAuth(unittest.TestCase):\n    def test_scope(self):\n        self.assertTrue(authorize('tenant-a', 'tenant-a'))\n        self.assertFalse(authorize('tenant-a', 'tenant-b'))\n\nif __name__ == '__main__': unittest.main()\n",
            "unrelated.txt": "preserve-me\n",
        },
        instructions="Fix the authority mismatch at the shared authorize boundary, preserve valid same-tenant requests and unrelated.txt, then run python -m unittest -v.",
        required_terms=("authorize", "unittest"),
        validation=("python-tests", "preserve-unrelated"),
    ),
    "file-markdown-report": FixtureSpec(
        files={
            "evidence/findings.json": '[{"severity":"high","file":"api.py","line":12,"issue":"tenant mismatch"},{"severity":"medium","file":"worker.py","line":44,"issue":"missing timeout"}]\n',
            "template.md": "# Audit report\n\n## Findings\n\n## Remediation plan\n",
        },
        instructions="Create audit-report.md from the evidence and template. Order findings by severity, include exact file:line references, keep remediation separately labeled, then publish audit-report.md with files.publish.",
        required_terms=("api.py:12", "worker.py:44", "Remediation plan"),
        validation=("audit-report.md",),
    ),
    "file-document-extract": FixtureSpec(
        files={
            "input/document.txt": "Invoice: INV-2048\nDate: 2026-09-20\nTotal: 318.40 USD\nSupplier: Example Labs\n",
            "schema.json": '{"invoice":"string","date":"YYYY-MM-DD","total_usd":"number","supplier":"string"}\n',
        },
        instructions="Extract input/document.txt into extracted.json matching schema.json exactly, publish it with files.publish, then report the output path and any uncertainty.",
        required_terms=("INV-2048", "318.4", "Example Labs"),
        validation=("extracted.json",),
    ),
    "operation-idempotent-write": FixtureSpec(
        files={
            "service.py": "import json, pathlib, sys\np=pathlib.Path('state.json'); s=json.loads(p.read_text()); key=sys.argv[1]\nif key not in s['keys']: s['keys'].append(key); s['writes'] += 1\np.write_text(json.dumps(s, sort_keys=True)+'\\n')\nprint(json.dumps(s, sort_keys=True))\n",
            "state.json": '{"keys":[],"writes":0}\n',
        },
        instructions="Execute the authorized write with idempotency key eval-key twice to simulate a retry, then independently read state.json and report whether exactly one write committed.",
        required_terms=("eval-key", "exactly one"),
        validation=("idempotent-state",),
    ),
    "operation-partial-reconcile": FixtureSpec(
        files={
            "state.json": '{"idempotency_key":"eval-key","committed":true,"writes":1}\n',
            "retry.py": "import json, pathlib\np=pathlib.Path('state.json'); s=json.loads(p.read_text()); s['writes'] += 1; p.write_text(json.dumps(s)+'\\n')\n",
        },
        instructions="The previous request timed out. Reconcile state.json before deciding whether to run retry.py. Do not duplicate a committed write and report the authoritative final state.",
        required_terms=("eval-key", "committed", "writes"),
        validation=("reconciled-state",),
    ),
    "memory-recovery-cross-session-preference": FixtureSpec(
        files={
            "memory/confirmed.json": '{"scope":"user-7","status":"confirmed","preference":"Use concise Chinese answers"}\n',
            "memory/distractor.json": '{"scope":"user-8","status":"confirmed","preference":"Use verbose English answers"}\n',
        },
        instructions="Use only confirmed memory for user-7, exclude other scopes, and write memory-result.json with selected_scope, selected_preference, excluded_scopes, replayed=false and writes=1. Independently read it back; this local fixture does not require Artifact publication.",
        required_terms=("user-7", "concise Chinese", "user-8"),
        validation=("memory-result.json",),
    ),
    "memory-recovery-postwrite-reconcile": FixtureSpec(
        files={
            "receipts/write.json": '{"effect_id":"effect-9","idempotency_key":"write-9","status":"committed","writes":1}\n',
            "state.json": '{"effect_id":"effect-9","writes":1}\n',
        },
        instructions="Reconcile the unknown completion using receipts/write.json and state.json. Do not replay the committed effect. Write recovery-result.json with replayed=false, writes=1, and receipt_status, then independently read it back; this local fixture does not require Artifact publication.",
        required_terms=("effect-9", "committed", "replayed"),
        validation=("recovery-result.json",),
    ),
}
