# Wave 5 P3A Product Gate Report — Zebra fix-v4 compatibility candidate

Date: 2026-08-21

| Gate | Result |
| --- | --- |
| Durable goal/root/projection contract | PASS |
| Legacy stream projection compatibility | PASS |
| Stable Task / on-demand provider selection | Local deterministic PASS — `[0, 0, 1, 0]` |
| USER/SYSTEM/trusted-context boundary | Local deterministic PASS — raw USER, server-resolved Domain Contract/selected Skill in SYSTEM, digest-bound minimal context |
| Frozen general read-capability boundary | Local deterministic PASS |
| Public projection privacy | Local deterministic PASS — no SYSTEM/trusted private-body leakage |
| Zebra P3A + cited stream regression set | PASS — 83 tests |
| Zebra trusted-context/digest contract | PASS — 20 tests |
| Exact Zebra full command | Base-matched — current 2326 / 9 / 9, exact `bbb6654` 2317 / 9 / 9, same failure IDs |
| FinOS `c2f5f1a` compatibility | Base-matched except 8 registered Gate-0 red records; candidate-only Milestone2 records are green |
| Deployed staging / real provider | NOT RUN / BLOCKED |
| P3A Product Gate | NOT CLOSED |
| Final-SHA Closure | NOT CLOSED |

Zebra implementation is `4d62d74e7e6c50573f3fd0a20190bd74cfb09271`; compatible
FinOS implementation is `bb1a63dd6f9b29b71f58dd842e18b07dcb0645c0`, with
required ancestors `c2f5f1a455649fdf54dd0d0c23089978367c6b23` and
`8dd2c25704190769e3f30d282318ed189a0e5695`. Fix-v3 audit refs remain
unchanged. All v4 refs are local and unpushed.

The reviewed capture is owned by FinOS at
`docs/wave5-p3a/real-model/p3a-local-evidence.json`, SHA-256
`05e519d31a927414ae1873953ac3c0852f22305244d1ce9044721e5adcc893ab`.
It uses an actual local FinOS API → Zebra HTTP → durable store → Worker →
ContextCompiler → ModelGateway path, but its model endpoint is a deterministic
OpenAI-compatible stub, not DeepSeek/Qwen or deployed staging. It records
non-null task/turn IDs, raw USER messages, trusted SYSTEM guidance, frozen
trusted context, signed owner-scoped `positions.list` evidence, and unchanged
Core fingerprint without credentials or raw tool arguments.

The full Zebra command was `.venv/bin/python -m pytest -q`. The exact base
comparison has nine identical failures and nine skips; current has nine added
passing tests from P3A work. The changed source passes Ruff and contract tests.
Ruff/mypy diagnostics in the legacy digest test/validator are unchanged from
`bbb6654` and were not modified to hide unrelated debt.

The corrected local deterministic compatibility gate is PASS. **Product Gate
and Final-SHA Closure remain NOT CLOSED** pending separately authorized real
provider/staging and remote closure. No push, PR, merge, deploy, frontend/web
change, Core write, or P3B/C/D/5.5 work occurred.
