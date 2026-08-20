# Wave 5 P3A Product Gate Report — Zebra fix-v3

Date: 2026-08-20

| Gate | Result |
| --- | --- |
| Durable goal/root/projection contract | PASS |
| Legacy stream projection compatibility | PASS |
| Stable Task / on-demand provider selection | Local deterministic PASS |
| Trusted AgentDefinition context boundary | Local deterministic PASS — USER is exact raw turn text |
| Frozen general read-capability boundary | Local deterministic PASS |
| Focused Zebra regression | PASS — 83 tests |
| Deployed staging / real provider | NOT RUN / BLOCKED |
| P3A Product Gate | NOT CLOSED |
| Final-SHA Closure | NOT CLOSED |

Zebra implementation:
`26780f4f9a254f8d332fa1a7f8957f8cf7c50fc2`. Compatible FinOS implementation:
`18aadd2d395f851f1e8422ee3086361699d8672f`. The evidence used Zebra checkout
`f70ef8262985589ed740d037acef131f94bfc6cc`. All fix-v3 refs remain local and
unpushed. Frozen evidence is owned by FinOS at
`docs/wave5-p3a/real-model/p3a-local-evidence.json`, SHA-256
`4e138f8d3ce7ed1fda2e8e6773dd2380fac3373d699f2bc5569fc8c59b0b2f84`.

The local integration uses an actual Zebra HTTP API, durable store, Worker,
ContextCompiler, and ModelGateway, but the OpenAI-compatible model endpoint is
deterministic. It is not a DeepSeek/Qwen or deployed-staging result. Its A
USER messages are exact raw turn text; trusted Domain Contract/Skill guidance
stays in SYSTEM context, and the general provider scope cannot expand after
Task creation.

The full Zebra failure set matches exact synchronized `bbb6654`; cited
legacy-stream checks pass on both current and base. No new Zebra failure is
attributed. No remote verification, push, PR, merge, deploy, frontend/web/UI
work, or P3B/C/D/5.5 work occurred.

Stop at the corrected local P3A gate.
