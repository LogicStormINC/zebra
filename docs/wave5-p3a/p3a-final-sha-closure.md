# Wave 5 P3A Final-SHA Closure — Zebra fix-v3

Date: 2026-08-20

| Item | Value |
| --- | --- |
| Branch | `codex/znx-wave5-p3a-fix-v3` (local, unpushed) |
| Exact fix-v2 base | `bbb6654e12a6154da657151abe38a208626413c9` |
| P3A implementation | `26780f4f9a254f8d332fa1a7f8957f8cf7c50fc2` |
| Compatible FinOS implementation | `18aadd2d395f851f1e8422ee3086361699d8672f` |
| Zebra checkout recorded by this evidence | `f70ef8262985589ed740d037acef131f94bfc6cc` |
| Frozen local evidence owner | FinOS `docs/wave5-p3a/real-model/p3a-local-evidence.json` |
| Evidence SHA-256 | `4e138f8d3ce7ed1fda2e8e6773dd2380fac3373d699f2bc5569fc8c59b0b2f84` |

## Corrected local evidence

- `TaskPreparedPayload` omits default conversational/empty goal fields from
  legacy stream projections while preserving explicit `goal_bound` data.
- Root goal events and projections retain latest goal revision across handoff,
  compaction, recovery, and Worker reconstruction. Conversational tasks keep
  no active goal anchor and use the current turn.
- The actual local FinOS → Zebra HTTP → durable store → Worker →
  ContextCompiler → ModelGateway chain records one Stable Task with four
  durable turns and per-turn `finos.*` execution counts `[0, 0, 1, 0]`.
  Zebra does not route financial intent or escalate grants; the model selects
  the already-signed provider tool.
- Trusted `system://finos-aceagent-domain-contract` guidance contributes to
  the resolved digest and is a SYSTEM message. Every A USER message is the
  exact original turn text: no temporal/page/account wrapper, preloaded FinOS
  context pack, or duplicated Skill text.
- FinOS freezes general Task `finos_read_capabilities` at root creation. A
  later Skill expansion cannot widen a continuation's Zebra provider scope;
  missing or malformed snapshots fail closed while the daily typed-command
  compatibility contract remains green.

## Verification

```text
Zebra focused P3A + cited legacy stream regressions: 83 passed
FinOS focused P3A contract suite: 22 passed
```

Zebra's identical full command has the same nine failing IDs as exact
synchronized `bbb6654` (current `2257 passed, 8 skipped`; base `2249 passed,
8 skipped`). FinOS full discovery reports the same 23 failure IDs as exact
`2532c2e` (current 947 discovered; base 949); the deterministic evidence is
hashed above.

## Disposition

The corrected **local deterministic integration gate is PASS**. The model is a
deterministic OpenAI-compatible stub, not a real provider or deployed staging.

**Product Gate is NOT CLOSED. Final-SHA Closure is NOT CLOSED.** Staging and a
real-provider run are NOT RUN / BLOCKED without endpoint or authority. No
remote verification, push, PR, merge, deploy, frontend/web/UI work, or
P3B/C/D/5.5 work occurred. Stop at P3A.
