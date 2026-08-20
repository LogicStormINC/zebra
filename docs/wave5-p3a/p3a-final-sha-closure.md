# Wave 5 P3A Final-SHA Closure — Zebra fix-v4 compatibility candidate

Date: 2026-08-21

| Item | Value |
| --- | --- |
| Branch | `codex/znx-wave5-p3a-fix-v4` (local, unpushed) |
| Exact Zebra base | `bbb6654e12a6154da657151abe38a208626413c9` |
| Zebra implementation | `4d62d74e7e6c50573f3fd0a20190bd74cfb09271` |
| Compatible FinOS implementation | `bb1a63dd6f9b29b71f58dd842e18b07dcb0645c0` |
| Required FinOS compatibility ancestor | `c2f5f1a455649fdf54dd0d0c23089978367c6b23` |
| Frozen local evidence owner | FinOS `docs/wave5-p3a/real-model/p3a-local-evidence.json` |
| Evidence SHA-256 | `05e519d31a927414ae1873953ac3c0852f22305244d1ce9044721e5adcc893ab` |

## Corrected local evidence

- `TaskPreparedPayload` preserves the frozen legacy stream projection when
  conversational goal fields are absent/default, and retains explicit goal
  data when present.
- The server-resolved Domain Contract, selected trusted Skill, and opaque
  structured metadata all contribute to one resolved-context digest. Zebra
  keeps the metadata generic and grants no FinOS authority from it.
- The local integration capture records one four-turn Stable Task with raw
  USER messages, `[0, 0, 1, 0]` tool counts, one pre-authorized signed
  owner-scoped `positions.list` read on demand, and no public projection leak.
- Journal goal revision/compaction/recovery retain the same selected definition
  digest. No financial routing, mutable grant escalation, or second loop was
  added to Zebra.

## Verification

```text
Zebra P3A + cited legacy stream focused suite: 83 passed
Zebra trusted structured-context / digest suite: 20 passed
FinOS P3A/root/acceptance/Slice6D suite: 29 passed
FinOS Journal/Data Confirmation successor: 136 passed
FinOS UI shell: 136 passed
```

The identical Zebra full command `.venv/bin/python -m pytest -q` reports
current `2326 passed, 9 failed, 9 skipped`; exact `bbb6654` reports `2317
passed, 9 failed, 9 skipped`. All nine failure IDs match. FinOS full discovery
is current `950 / 13 failures / 7 errors / 16 skipped` versus exact `c2f5f1a`
`923 / 5 failures / 7 errors / 16 skipped`; the eight additional failures are
the registered Gate-0 red records, not Milestone2 or Journal/UI regressions.

Ruff/mypy changed-path checks retain only base diagnostics in unrelated legacy
lines; the new resolver and context contracts are covered by the 20 green
tests. No UI/frontend/web path changed in this Zebra correction.

## Disposition

**Local deterministic compatibility gate: PASS. Product Gate: NOT CLOSED.
Final-SHA Closure: NOT CLOSED.** The capture is not real DeepSeek/Qwen or
deployed staging evidence. Remote verification, push, PR, merge, and deploy
are absent and not authorized. This document deliberately does not claim its
own commit SHA; the handoff reports the actual document HEAD.
