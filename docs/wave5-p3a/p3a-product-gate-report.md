# Wave 5 P3A Product Gate Report — Zebra fix-v3

Date: 2026-08-20

| Gate | Result |
| --- | --- |
| Durable goal/root/projection contract | PASS |
| Legacy stream projection compatibility | PASS |
| Stable Task / on-demand provider selection | Local deterministic PASS |
| Trusted AgentDefinition context boundary | Local deterministic PASS |
| Focused Zebra regression | PASS — 83 tests |
| Deployed staging / real provider | NOT RUN / BLOCKED |
| P3A Product Gate | NOT CLOSED |
| Final-SHA Closure | NOT CLOSED |

Zebra implementation:
`26780f4f9a254f8d332fa1a7f8957f8cf7c50fc2`. Compatible FinOS implementation:
`ff03023f7f51c776063a5100af5a4cbab654bbd6`. Both fix-v3 refs remain local and
unpushed. Frozen evidence is owned by FinOS at
`docs/wave5-p3a/real-model/p3a-local-evidence.json`, SHA-256
`0394a9f417a1755e79614423002a01f8d12601534dd334e3961fded6d901b083`.

The local integration uses an actual Zebra HTTP API, durable store, Worker,
ContextCompiler, and ModelGateway, but the OpenAI-compatible model endpoint is
deterministic. It is not a DeepSeek/Qwen or deployed-staging result.

The full Zebra failure set matches exact synchronized `bbb6654`; no new Zebra
failure is attributed. No remote verification, push, PR, merge, deploy,
frontend/web/UI work, or P3B/C/D/5.5 work occurred.

Stop at the corrected local P3A gate.
