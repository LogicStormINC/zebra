# Live Agent Evaluation Suite

This suite measures Zebra through real dependencies or a real provider-backed
model. It is deliberately separate from deterministic protocol tests.

## Fixed matrix

- `cases/` contains 60 fixed tasks: answer, research, code, file, operation,
  and memory/recovery each contain 10.
- Every category has six development cases and four holdout cases.
- Every case has exactly three independent repetitions: 180 attempts total.
- Every case declares typed fixture inputs plus verifier evidence and
  postcondition assertions.
- The case plan never creates attempts:

```bash
uv run python scripts/live_eval_plan.py > /tmp/zebra-live-eval-plan.jsonl
```

## Evidence boundary

An attempt is not a model-written success claim. `live_eval_run.py` invokes two
separate programs:

1. a runner that operates Zebra and returns runtime capture data;
2. the case's external postcondition verifier, which checks durable state,
   artifacts, receipts, citations, or repository checks.

The runner identity comes from an operator-owned config, not its stdout.
`zebra_real_model` additionally requires Zebra session/turn ids, provider
model-call ids, and independent verifier attestation against authoritative
runtime evidence. `scripted` captures are retained for harness testing but can
never count in `real_model` or `real_dependency` reports. Digests make later
capture/verifier edits detectable; they are integrity checks, not signatures.

Runner config:

```json
{
  "schema": "zebra.live-eval-runner-config.v1",
  "kind": "zebra_real_model",
  "runner_id": "production-zebra-runner",
  "runtime": "zebra-cloud-agent",
  "provider": "deepseek",
  "model": "configured-real-model",
  "argv": ["/absolute/path/to/zebra-live-runner"]
}
```

The runner reads one `zebra.live-eval-request.v1` JSON object from stdin. It
must return one JSON object containing:

- a unique `attempt_id` and timezone-aware `started_at` / `finished_at`;
- `session_id`, `turn_id`, and non-empty `model_call_ids`;
- `terminal_outcome` and `completion_claimed`;
- `human_intervention`, `repeated_tool_calls`;
- `first_public_feedback_ms`, `total_duration_ms`, and nullable `cost_usd`.

Verifier config:

```json
{
  "schema": "zebra.live-eval-verifier-config.v1",
  "kind": "external_postcondition",
  "verifier": "answer.authority-boundary.v1",
  "argv": ["/absolute/path/to/authority-boundary-verifier"]
}
```

The verifier receives the request, runner identity, and capture on stdin. It
must return the exact case verifier and ordered assertions, evidence references,
nullable citation/recovery judgments, plus:

```json
{
  "runner_attested": true,
  "attestation_evidence": ["zebra:model-call:<authoritative-id>"]
}
```

Run one attempt only when those external programs and their real fixtures exist:

```bash
uv run python scripts/live_eval_run.py \
  --case-id answer-authority-boundary \
  --repetition 1 \
  --runner-config /secure/runner.json \
  --verifier-config /secure/verifier.json \
  --attempts /evidence/attempts.jsonl
```

No runner or verifier fixtures that fabricate a passing result are shipped.

## Reporting

```bash
uv run python scripts/live_eval_report.py \
  --attempts /evidence/attempts.jsonl \
  --evidence-tier real_model
```

The report exits with status 2 and withholds all rates until all 180 attempts
for the selected evidence tier are present. Duplicate, out-of-range, tampered,
unknown-case, wrong-verifier, incomplete-evidence, or assertion-mismatch
attempts fail closed. Reused attempt, session/turn, or model-call identities are
also rejected, so one real execution cannot fill several repetitions. Provider
cost may remain unavailable; it is never treated as zero.
