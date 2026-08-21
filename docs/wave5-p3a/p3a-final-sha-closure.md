# Wave 5 P3A Final-SHA Closure — Zebra fix-v4 compatibility candidate

Date: 2026-08-21

| Item | Value |
| --- | --- |
| Branch | `codex/znx-wave5-p3a-fix-v4` (published without force; initial remote ref equals `3c6800c96e66dae8c6d2c71444789eed10cc0efa`) |
| Exact Zebra base | `bbb6654e12a6154da657151abe38a208626413c9` |
| Zebra implementation | `532127cd5c532d00dab5b415d9d645b760eedbee` |
| Compatible FinOS implementation | `a86d89dc05d6b439d3e8b0a9119235383d80b4d4` |
| Required FinOS compatibility ancestor | `c2f5f1a455649fdf54dd0d0c23089978367c6b23` |
| Frozen local evidence owner | FinOS `docs/wave5-p3a/real-model/p3a-local-evidence.json` |
| Evidence SHA-256 | `513c824684a9212f309ced569826a4eae078cf0562021c3214d69bf119eed518` |
| Staging evidence owner | FinOS `docs/wave5-p3a/real-model/p3a-staging-evidence-20260821.json` |
| Staging evidence SHA-256 | `4f4bc63abffcfc1d355415d4a0cdde10fd454f9e297cc5eab8aaf216a5677bb2` |

## Local closure evidence

The capture proves the real local HTTP/durable runtime path with a deterministic
OpenAI-compatible stub: one Stable Task/four durable turns, raw USER messages,
server-resolved SYSTEM guidance, typed digest-bound context, one on-demand
signed `positions.list` read, `[0, 0, 1, 0]` execution counts, no public
projection leak, unchanged Core fingerprint, and Journal goal/recovery
continuity.

The P1 correction blocks direct client `trust_policy` and free SYSTEM text,
requires a typed MAC-bound claim with a system/Skill ref, and fails context-only
creation before Worker execution. P2 regression coverage proves valid
server-side context/digest persistence with raw-claim exclusion, and rejects
tampering or absent API authentication.
It keeps Zebra provider-neutral; no business type, tool, second loop, or second
state machine was introduced.

## Authorized staging evidence and blocker

The published immutable pair was deployed only to staging with a verified
backup/rollback record. Both remote candidate refs were read back at their
exact implementation/document base SHA before this evidence-only update.
Authenticated staging checks prove DeepSeek V4 Flash and live Qwen
`qwen3.7-max-2026-05-17` (`qwen-max-dated-thinking-v1`) each completed a
separate public → pronoun → personal-finance → public Stable Task. Their
durable events show raw USER bodies, a frozen resolved digest, one signed
owner/account-scoped typed read, `[0, 0, 1, 0]`, canonical finals and usage,
and a public projection without trusted/system body, grants, tokens, raw
arguments, or tool output.

The required actual Journal goal-bound lane blocked before its revision and
compaction/recovery checks. FinOS Task `70d67e32ba794353a3b990ccfa5f9187` /
Zebra Task `c08c4bc4-81b8-4808-af08-9bbee6f67cb1` persisted `TASK_GOAL_SET`,
then emitted three `finish_reason=tool_calls` model responses, proposed 9
calls, and executed 8 read-only FinOS calls. The unexecuted `files.list`
call was policy-denied for `files.list path argument path escapes workspace`;
the nonretryable session summary is `tool call blocked by policy`, its terminal
reason is null, and no completion contract exists. The missing final/artifact
is a consequence of that denial, not a response-recovery prerequisite.

The root-path audit classifies the stop as **b: existing shared generic policy
behavior**, not a P3A provider-grant or trusted-context defect. The durable
AgentDefinition resolves the Domain Contract and frozen Journal Skill with
typed-only context and a digest; its signed `finos.journals.v2` grant is
separate from the pre-P3A `general` read-only profile that exposes
`files.list`. Current and exact-`bbb6654` shared-policy selections both pass
73/73. No P3A production change, P3B code, manual retry, or second loop was
added. Browser smoke was not run after the blocker.

FinOS evidence also records reproducible PostgreSQL before/after proof: the
container identity/start time and canonical schema SHA-256 are equal, selected
Core/Journal counts are unchanged, and runtime-only rows increase by 9 tasks
and 8 artifacts. A compatible pre-deploy full-row fingerprint is absent, so
that remains an explicit evidence gap rather than a false equality claim.

## Compatibility matrix

| Row | Paths | Result |
| --- | --- | --- |
| FinOS `8dd2c25` | `finos/registered_journal.py`, registered-journal tests | inherited actual ancestor; untouched |
| FinOS `c2f5f1a` | `web/app.js`, `web/index.html`, UI-shell test | inherited actual ancestor; untouched |
| This Zebra correction | generic AgentDefinition resolver/context and tests | no FinOS business or UI type added |
| Planning branch | `aad409e` | not an ancestor; no merge, rebase, or cherry-pick |

| Gate | Result |
| --- | --- |
| Zebra P3A + legacy stream + trusted-context focused command | 110 passed; includes three P2 signed-claim persistence/negative contracts |
| FinOS combined P3A/root/acceptance/Slice6D command | 31 passed |
| FinOS Milestone2 boundary assertions | 3 passed |
| FinOS Journal/Data Confirmation successor | 136 passed |
| FinOS UI shell | 136 passed |
| Zebra generic policy current/base probe | 73/73 current and 73/73 exact `bbb6654` archive |
| Zebra full vs exact `bbb6654` | `2333 passed, 9 failed, 9 skipped` vs `2317 passed, 9 failed, 9 skipped`; IDs identical |
| FinOS full vs exact `c2f5f1a` | `Ran 952; failures=9, errors=7, skipped=16` vs `Ran 923; failures=1, errors=7, skipped=16`; eight candidate-only Gate-0 red outcomes |

Zebra changed-source Ruff/mypy and `git diff --check` pass. FinOS `compileall`,
JSON validation, and `git diff --check` pass; FinOS has no installed Ruff module.

## Disposition

**Local deterministic compatibility gate: PASS. Product Gate: NOT CLOSED.
Final-SHA Closure: NOT CLOSED.** The new capture includes real providers and
staging, but the required Journal final/artifact is absent after an existing
shared generic policy stop. Candidate refs were pushed and staging-only
deployment was performed; no PR, merge, production deployment, P3A production
fix, or P3B work occurred. This document does not claim its own commit SHA;
the handoff reports the actual post-commit document HEAD.
