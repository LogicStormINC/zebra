# Wave 5 P3A Product Gate Report — Zebra fix-v4 compatibility candidate

Date: 2026-08-21

| Gate | Result |
| --- | --- |
| Durable goal/root/projection contract | PASS |
| Legacy stream projection compatibility | PASS |
| Stable Task / on-demand provider selection | Local deterministic PASS — `[0, 0, 1, 0]` |
| Raw USER / SYSTEM / trusted context | Local deterministic PASS — raw USER; resolved Domain Contract/selected Skill in SYSTEM; typed context digest-bound |
| Client SYSTEM-injection boundary | PASS — public parser rejects `trust_policy`; raw free text cannot enter the SYSTEM renderer |
| Signed context binding | PASS — the claim is bounded and MAC-bound to agent/refs/context; only its server-side bound context/digest persists, while tampering, absent API auth, or context-only creation are rejected |
| Frozen general read-capability boundary | Local deterministic PASS |
| Public projection privacy | Local deterministic PASS — no SYSTEM/trusted private-body leakage |
| Zebra P3A + legacy stream + trusted-context set | PASS — 110 tests |
| Exact Zebra full command | Base-matched — current 2333 passed / 9 failed / 9 skipped, exact `bbb6654` 2317 / 9 / 9, same failure IDs |
| FinOS `c2f5f1a` compatibility | Base-matched except 8 registered Gate-0 red records; no candidate-only Milestone2 record |
| Deployed staging / real provider | NOT RUN / BLOCKED |
| P3A Product Gate | NOT CLOSED |
| Final-SHA Closure | NOT CLOSED |

Zebra implementation is `532127cd5c532d00dab5b415d9d645b760eedbee`; compatible
FinOS implementation is `a86d89dc05d6b439d3e8b0a9119235383d80b4d4`. Required FinOS
ancestors are `c2f5f1a455649fdf54dd0d0c23089978367c6b23` and
`8dd2c25704190769e3f30d282318ed189a0e5695`; `aad409e` is not an ancestor.
Fix-v3 audit refs remain unchanged. All v4 refs are local and unpushed.

## Trust-boundary result

The public `parse_agent_definition()` path now rejects client-supplied
`trust_policy`, digest, and raw skill guidance. A separate typed claim accepts
only timezone/current date, opaque source/account metadata, and enum
personality; free custom text and unproduced selected refs do not fit the
schema. The API verifies the MAC and requires a server-resolved system/Skill
reference before copying the resulting context into the durable definition and
computing its digest.

The claim and resolver are generic: Zebra adds no FinOS provider type, business
tool, route, state machine, or routing branch. Without authenticated transport
there is no fallback injection—the metadata is omitted.

## Frozen deterministic capture

FinOS owns the sole reviewed capture:
`docs/wave5-p3a/real-model/p3a-local-evidence.json`, SHA-256
`513c824684a9212f309ced569826a4eae078cf0562021c3214d69bf119eed518`.
It runs actual local FinOS API → Zebra HTTP → durable store → Worker →
ContextCompiler → ModelGateway, using a deterministic OpenAI-compatible stub,
not DeepSeek/Qwen or deployed staging.

Scenario A records non-null Stable Task/turn IDs, exact raw USER turns,
SYSTEM-only Domain Contract and frozen Skill, `custom_instructions_not_system`,
one signed owner-scoped `positions.list` read, `[0, 0, 1, 0]` tool counts,
and an unchanged Core fingerprint. Journal goal/recovery and public-projection
non-leakage are included without credentials or raw tool arguments.

## Verification

```text
.venv/bin/python -m pytest -q \
  tests/agent_core/test_harness_loop.py \
  tests/agent_core/test_session_bootstrap.py \
  tests/agent_storage/test_session_handoffs.py \
  tests/api/test_agent_definition_contract.py \
  tests/api/test_task_routes.py \
  tests/api/test_wave5_p3a_goal_contract.py \
  tests/worker/execution/test_core_execution.py \
  tests/agent_core/test_session_goals.py \
  tests/agent_core/test_session_projection.py \
  tests/api/test_api_app.py::test_api_get_session_stream_returns_persisted_events \
  tests/cli/test_cli_session_stream.py::test_cli_stream_lists_persisted_events \
  tests/agent_tools/test_agent_definition_context.py \
  tests/agent_core/test_agent_definition_digest.py
# 110 passed: the former 103 plus four P1 parser/binder contracts and three
# P2 signed-claim persistence/negative contracts.

uv run ruff check <changed Zebra source and API-contract paths>
uv run mypy <three changed Zebra source files>
# both passed
```

The exact full command `.venv/bin/python -m pytest -q` reports current
`2333 passed, 9 failed, 9 skipped`; exact `bbb6654` reports `2317 passed,
9 failed, 9 skipped`. The same nine failures are:

1. `test_deepseek_thinking_tool_response_requires_valid_reasoning_content`
2. `test_openai_compatible_gateway_parses_tool_calls`
3. `test_http_create_session_accepts_existing_definition_identity`
4. `test_api_pull_request_uses_broker_credential_for_github_execution`
5. `test_api_pull_request_missing_broker_credential_records_audit`
6. `test_api_pull_request_transport_failure_records_audit`
7. `test_api_pull_request_uses_proxy_transport_for_github_execution`
8. `test_api_pull_request_proxy_transport_failure_records_audit`
9. `test_repository_file_size_gate_passes`

FinOS identical discovery is `Ran 952 tests; FAILED (failures=9, errors=7,
skipped=16)` versus exact `c2f5f1a` `Ran 923 tests; FAILED (failures=1,
errors=7, skipped=16)`. Its eight candidate-only Gate-0 **red outcomes** are
separate from the runner categories and are not P3A, Milestone2, Journal, or
UI regressions.

## Disposition

**Local deterministic compatibility gate: PASS. Product Gate: NOT CLOSED.
Final-SHA Closure: NOT CLOSED.** Real-provider/staging and remote closure need
separate authority. No push, PR, merge, deploy, frontend/web change, Core
write, or P3B/C/D/5.5 work occurred.
