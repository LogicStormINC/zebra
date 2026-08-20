# Wave 5 P3A Final-SHA Closure — Zebra fix-v4 compatibility candidate

Date: 2026-08-21

| Item | Value |
| --- | --- |
| Branch | `codex/znx-wave5-p3a-fix-v4` (local, unpushed) |
| Exact Zebra base | `bbb6654e12a6154da657151abe38a208626413c9` |
| Zebra implementation | `532127cd5c532d00dab5b415d9d645b760eedbee` |
| Compatible FinOS implementation | `a86d89dc05d6b439d3e8b0a9119235383d80b4d4` |
| Required FinOS compatibility ancestor | `c2f5f1a455649fdf54dd0d0c23089978367c6b23` |
| Frozen local evidence owner | FinOS `docs/wave5-p3a/real-model/p3a-local-evidence.json` |
| Evidence SHA-256 | `513c824684a9212f309ced569826a4eae078cf0562021c3214d69bf119eed518` |

## Local closure evidence

The capture proves the real local HTTP/durable runtime path with a deterministic
OpenAI-compatible stub: one Stable Task/four durable turns, raw USER messages,
server-resolved SYSTEM guidance, typed digest-bound context, one on-demand
signed `positions.list` read, `[0, 0, 1, 0]` execution counts, no public
projection leak, unchanged Core fingerprint, and Journal goal/recovery
continuity.

The P1 correction blocks direct client `trust_policy` and free SYSTEM text,
requires a typed MAC-bound claim with a system/Skill ref, and fails context-only
creation before Worker execution. It keeps Zebra provider-neutral; no business
type, tool, second loop, or second state machine was introduced.

## Compatibility matrix

| Row | Paths | Result |
| --- | --- | --- |
| FinOS `8dd2c25` | `finos/registered_journal.py`, registered-journal tests | inherited actual ancestor; untouched |
| FinOS `c2f5f1a` | `web/app.js`, `web/index.html`, UI-shell test | inherited actual ancestor; untouched |
| This Zebra correction | generic AgentDefinition resolver/context and tests | no FinOS business or UI type added |
| Planning branch | `aad409e` | not an ancestor; no merge, rebase, or cherry-pick |

| Gate | Result |
| --- | --- |
| Zebra P3A + legacy stream + trusted-context focused command | 107 passed |
| FinOS combined P3A/root/acceptance/Slice6D command | 31 passed |
| FinOS Milestone2 boundary assertions | 3 passed |
| FinOS Journal/Data Confirmation successor | 136 passed |
| FinOS UI shell | 136 passed |
| Zebra full vs exact `bbb6654` | `2330 passed, 9 failed, 9 skipped` vs `2317 passed, 9 failed, 9 skipped`; IDs identical |
| FinOS full vs exact `c2f5f1a` | `952 / 13 / 7 / 16` vs `923 / 5 / 7 / 16`; only 8 registered Gate-0 reds added |

Zebra changed-source Ruff/mypy and `git diff --check` pass. FinOS `compileall`,
JSON validation, and `git diff --check` pass; FinOS has no installed Ruff module.

## Disposition

**Local deterministic compatibility gate: PASS. Product Gate: NOT CLOSED.
Final-SHA Closure: NOT CLOSED.** The capture is not real DeepSeek/Qwen or
deployed staging evidence. Remote verification, push, PR, merge, and deploy
remain absent and unauthorized. This document does not claim its own commit
SHA; the handoff reports the actual post-commit document HEAD.
