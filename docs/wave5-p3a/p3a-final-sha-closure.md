# Wave 5 P3A Final-SHA Closure — Zebra fix-v3

Date: 2026-08-20

| Item | Value |
| --- | --- |
| Branch | `codex/znx-wave5-p3a-fix-v3` (local, unpushed) |
| Exact fix-v2 base | `bbb6654e12a6154da657151abe38a208626413c9` |
| P3A implementation | `26780f4f9a254f8d332fa1a7f8957f8cf7c50fc2` |
| Compatible FinOS implementation | `ff03023f7f51c776063a5100af5a4cbab654bbd6` |
| Frozen local evidence owner | FinOS `docs/wave5-p3a/real-model/p3a-local-evidence.json` |
| Evidence SHA-256 | `0394a9f417a1755e79614423002a01f8d12601534dd334e3961fded6d901b083` |

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
  the resolved digest and is a SYSTEM message. The USER turn has neither a
  preloaded FinOS context pack nor duplicated Skill text.

## Verification

```text
Zebra focused P3A + cited legacy stream regressions: 83 passed
FinOS focused P3A contract suite: 20 passed
```

Zebra full suite has the same nine failing IDs as exact synchronized
`bbb6654` (current `2325 passed, 9 skipped`; base `2317 passed, 9 skipped`).
FinOS full discovery's current failures are all inherited from exact
`2532c2e`; the deterministic evidence is hashed above.

## Disposition

The corrected **local deterministic integration gate is PASS**. The model is a
deterministic OpenAI-compatible stub, not a real provider or deployed staging.

**Product Gate is NOT CLOSED. Final-SHA Closure is NOT CLOSED.** Staging and a
real-provider run are NOT RUN / BLOCKED without endpoint or authority. No
remote verification, push, PR, merge, deploy, frontend/web/UI work, or
P3B/C/D/5.5 work occurred. Stop at P3A.
