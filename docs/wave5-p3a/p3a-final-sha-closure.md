# Wave 5 P3A Final-SHA Closure — Zebra fix-v4 compatibility candidate

Date: 2026-08-20

| Item | Value |
| --- | --- |
| Branch | `codex/znx-wave5-p3a-fix-v4` (local, unpushed) |
| Exact fix-v2 base | `bbb6654e12a6154da657151abe38a208626413c9` |
| P3A implementation | `26780f4f9a254f8d332fa1a7f8957f8cf7c50fc2` |
| Compatible FinOS implementation | `5bbc4ac78375d33cb2a91a9be7dd08781b1ba3d4` |
| Required FinOS compatibility ancestor | `c2f5f1a455649fdf54dd0d0c23089978367c6b23` |
| Zebra checkout recorded by this evidence | `9c7a0666579dc2cb90f2294faea198eeb9bd6d32` |
| Frozen local evidence owner | FinOS `docs/wave5-p3a/real-model/p3a-local-evidence.json` |
| Evidence SHA-256 | `a973047b1d5aeb2aa4becaa4cfa712ece3fdeb94744768052bfd2dabcc346529` |

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
FinOS focused P3A/root/acceptance/typed-read/Slice6D suite: 26 passed
FinOS day-precision Journal/Data Confirmation: 111 passed
FinOS UI shell / immediate journal-list redraw: 136 passed
```

The audited exact Zebra command `.venv/bin/python -m pytest -q` has the same
nine failing IDs as exact `bbb6654` (current `2325 passed, 9 failed, 9
skipped`; base `2317 passed, 9 failed, 9 skipped`). FinOS is rebased onto
`c2f5f1a`, retaining its Journal/UI hotfix paths unchanged; its 19 P3A commits
replayed without conflicts. The FinOS full discovery comparison is current 949
tests (`15 failures, 8 errors, 16 skipped`) vs c2 923 (`5 failures, 7 errors,
16 skipped`): all 12 base records match, and the 11 extra records are carried
P3A Gate-0/Milestone2 contracts rather than compatibility-path regressions.

The exact full-suite environment is `.venv/bin/python` `3.12.13`, pytest
`8.4.2`, and:

```text
.venv/bin/python -m pytest -q
```

## Disposition

The corrected **local deterministic integration gate is PASS**. The model is a
deterministic OpenAI-compatible stub, not a real provider or deployed staging.

**Product Gate is NOT CLOSED. Final-SHA Closure is NOT CLOSED.** Staging and a
real-provider run are NOT RUN / BLOCKED without endpoint or authority. No
remote verification, push, PR, merge, deploy, new frontend/web/UI work, or
P3B/C/D/5.5 work occurred. Stop at P3A compatibility gate.
