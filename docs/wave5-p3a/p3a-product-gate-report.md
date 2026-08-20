# Wave 5 P3A Product Gate Report — Zebra fix-v4 compatibility candidate

Date: 2026-08-20

| Gate | Result |
| --- | --- |
| Durable goal/root/projection contract | PASS |
| Legacy stream projection compatibility | PASS |
| Stable Task / on-demand provider selection | Local deterministic PASS |
| Trusted AgentDefinition context boundary | Local deterministic PASS — USER is exact raw turn text |
| Frozen general read-capability boundary | Local deterministic PASS |
| Focused Zebra regression | PASS — 83 tests |
| FinOS `c2f5f1a` compatibility ancestry | PASS — 19 P3A commits, no conflicts |
| Exact Zebra full command | Base-matched — 9 failed / 9 skipped |
| Deployed staging / real provider | NOT RUN / BLOCKED |
| P3A Product Gate | NOT CLOSED |
| Final-SHA Closure | NOT CLOSED |

Zebra implementation:
`26780f4f9a254f8d332fa1a7f8957f8cf7c50fc2`. Compatible FinOS implementation:
`5bbc4ac78375d33cb2a91a9be7dd08781b1ba3d4`, with required ancestor
`c2f5f1a455649fdf54dd0d0c23089978367c6b23`. The evidence used Zebra v4
checkout `9c7a0666579dc2cb90f2294faea198eeb9bd6d32`. Fix-v3 audit refs remain
unchanged; all v4 refs are local and unpushed. Frozen evidence is owned by FinOS at
`docs/wave5-p3a/real-model/p3a-local-evidence.json`, SHA-256
`a973047b1d5aeb2aa4becaa4cfa712ece3fdeb94744768052bfd2dabcc346529`.

The local integration uses an actual Zebra HTTP API, durable store, Worker,
ContextCompiler, and ModelGateway, but the OpenAI-compatible model endpoint is
deterministic. It is not a DeepSeek/Qwen or deployed-staging result. Its A
USER messages are exact raw turn text; trusted Domain Contract/Skill guidance
stays in SYSTEM context, and the general provider scope cannot expand after
Task creation.

The full Zebra failure set matches exact `bbb6654` under
`.venv/bin/python -m pytest -q` (2325/2317 passed, 9 failed, 9 skipped).
FinOS day-precision and immediate Journal-list redraw gates remain green after
the ancestry-safe rebase. No remote verification, push, PR, merge, deploy,
new frontend/web/UI work, or P3B/C/D/5.5 work occurred.

Stop at the P3A compatibility gate.
