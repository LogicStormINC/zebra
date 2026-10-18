# Paused execution and skipped verifier repair

CLOUD-PAUSED-VERIFIER-01, 2026-10-18. Paired source delivery: Zebra
cloud-agent-trench and Trench main, local only.

## Root causes and smallest repair

Trench's shared Turn projector resolved waiting_input/awaiting_input before
reading authoritative delivery_assessment.partial/blocked. SDK timeline groups
regard waiting as live, so a paused, unverified Run kept the executing label.
The delivery outcome now takes precedence over waiting presentation. Explicit
error/cancel and current running/new-Turn precedence remain unchanged; genuine
completed tool activities remain completed, while the existing partial mapping
ends open activities. No SDK extension or package change was necessary.

NoopVerifier previously equated tool_status=executed with verification passed,
even though no verifier ran. It now returns passed=false with metadata.skipped=
true. Actual tool status/output and configured verifier behavior are unchanged.
The shared retry planner ignores explicit skipped metadata and the historical
skipped-hook sentinel, so a skipped check is neither a verified constraint nor
a failed check demanding another attempt. Fresh post-mutation evidence and
contract verification gates are unchanged.

Existing canonical Events, including old passed=true/skipped-hook records, are
immutable history and were not rewritten. The two historical Runs retain their
authoritative partial/unverified delivery. New hook results and their emitted
TESTS_COMPLETED metadata correctly expose false/skipped; this is proven without
issuing another real model request.

## Validation

- Red-first: two skipped-hook/retry checks and three paused-state projection
  cases reproduced the defects before source changes.
- Complete agent-core regression: 1,712 passed, 1 skipped. After adding an
  emitted-event regression, five focused hook/evidence checks passed.
- Frontend: 45 projection/thread/assistant-content tests passed. Tests preserve
  completed activities and active/new-Turn behavior while partial/blocked wins
  over waiting. Targeted Ruff/ESLint and diff checks passed.
- Derived network-disabled image: 33 original verification-default/freshness
  safety cases, three skipped/retry/event checks and actual configured verifier
  checks passed. The same checks passed in the updated normal Worker process.
- Worker-only overlay replaces exactly hooks.py and retry_plan.py on87505c5e;
  base module bytes matched the source parent. No dependency/base pull required.
  New image zebra-worker:paused-verifier-01 SHA256
  d814124b0993c546c4733c0ae40b6fd8948981011841355a206aaa5a8669d38a.

The shared Worker was initially occupied by independent stage-G diagnostics;
base-image and lease guards prevented replacement. User-authorized coordination
waited for restored_and_released, then exact environment/command/mount/security/
resource preflight and no-active-lease checks preceded activation. Worker is
healthy/restart0; configured high/v2 and Trench suggestion-dedupe sources remain
unchanged. API/Search image/ID/start/restart/health and Exa control are preserved.
Full dynamic HostConfig diagnostic hashes are not used as an equality claim.

## Existing Run page acceptance, no model replay

- change: conversation conv_1792323938793_608b93, Run
  5c9afa1f-f8bc-45a5-b203-6ea1f7faeb1f.
- operate: conversation conv_1792324017506_44ddf3, Run
  52ce78cc-8599-458a-aca8-3c74b6c4ffc2.

Both authenticated real pages were reloaded with unchanged backend data and no
response interception. Execution process badges now show 部分完成 and no longer
执行中; their retained text states that independent verification is missing and
the task is paused. Canonical event counts for both Sessions exactly match the
saved original sample: two model requests/responses, one write and one suspended
outcome each. No new model/tool/Run was generated. No claim of complete network
POST-window coverage is made from an evicted browser event buffer.

Two older protected partial Turn answer/request/metadata hashes are identical
before/after. Model/tool counters are identical across the post-handoff update
and offline checks, active leases0. No old Run reexecution, original status
rewrite, search, provider configuration change, schema migration, push or remote
deployment. Trench dirty registry, next-env and untracked user work were kept.

Private receipts under .artifacts/cloud-paused-verifier-01/ in the task worktree:
before/after, acceptance.json, frozen offline check scripts and change/operate
page screenshots. Trench source commit80f3896. Shared-resource handoff includes
the new normal image so later diagnostics do not roll this fix back.
