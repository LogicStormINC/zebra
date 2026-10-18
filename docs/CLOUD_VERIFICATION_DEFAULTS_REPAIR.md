# Explicit mutation contract verification defaults

Task: CLOUD-VERIFICATION-DEFAULTS-01, 2026-10-18.

## Cause and minimal repair

`parse_task_contract` previously selected the explicit Host task type but inherited
missing verification fields from text inference. An explicit change/operate
contract with an explanatory goal could therefore omit verification and its
matching action outcome. Defaults now follow the final mutation type, replacing
the opposite type-specific default while preserving generic inferred outcomes.
Explicit requireVerification and requiredOutcomes fields remain authoritative;
this does not exempt actual observed mutations from fresh evidence checks.

`needs_post_mutation_verification` previously returned false when no read-only
tool was available. Capability absence was consequently interpreted as evidence
satisfaction. Freshness now depends on recorded mutation and verification epochs,
including per-resource coverage, regardless of read capability. Valid existing
proof and explicit postcondition receipts remain accepted.

The shared finalization capability check also requires a read-only tool before
asking for another verification round. Without capability or budget, unverified
writes suspend with verification_required rather than pass or request an
impossible additional round. This changes no semantic classifier, keywords,
prompts, provider, schema, Trench logic or suggestion de-duplication.

## Offline acceptance

- Red-first reproduction: 13 failed, 14 passed before the repair.
- Complete agent-core regression: 1,710 passed, 1 skipped (11.78 s).
- Existing standalone search-intent and publication-date checks passed.
- Targeted Ruff and git diff --check passed.
- New checks cover both task-type field spellings, final change/operate defaults,
  explicit Host overrides, missing/stale/fresh/global/per-resource proof, and
  scripted harness termination without an extra model/tool round.
- Two existing outcome-matching tests now include fresh verification so they
  continue testing outcome matching rather than relying on the removed bypass.

No external model or search request was made. Harness completions are scripted.
Initial source-only acceptance did not rebuild or restart services. The separately
authorized local activation is recorded below; no model/page E2E is claimed.

The two protected original Turns remain partial, high/transient_v2 with their
original feedback. Answer/request/metadata hashes match the prior saved snapshot.
Local delivery targets cloud-agent-trench only; no push or deployment.

## Authorized local Worker activation

User authorized Worker-only update after source integration. Derived image
`zebra-worker:verification-defaults-01` replaces exactly task_contracts.py,
tool_freshness.py and final_completion.py on the then-normal c0f0380c base.
All three base modules matched the repair parent commit before replacement.
No dependency installation or base-image pull was performed.

The first activation was correctly stopped by the container-ID guard because
the independent performance task had switched the shared Worker to a diagnostic
image. With explicit user authorization, coordination waited for that task to
finish its batch, restore the original normal image and release the Worker via
its stage-e/worker-handoff.safe.json. No diagnostic process was overwritten.
A fresh activation baseline was taken after handoff, excluding the other task's
model/tool activity from this acceptance window.

- Fresh targeted source regression: 47 passed.
- Derived image, network disabled: 33 standalone cases passed.
- Actual updated normal Worker subprocess: the same 33 cases passed using
  scripted completions and fake tools only. Explicit change/operate defaults,
  stale/missing/global/resource evidence, valid receipts and truthful suspension
  are covered. Missing read capability consumes exactly two scripted completions
  and one fake mutation; no invalid extra verification round.
- Exact three-module source hashes; healthy Worker, restart count zero and no
  startup errors or diagnostic probe. Image SHA256:
  87505c5e0eda972d028ae25be3eb79025c74f1a348bcdd89130f047e6df74e8b.
- Full effective configuration hash unchanged, preserving runtime model settings
  and v2. API/Search IDs, image/start/restart/config receipts unchanged.
- Model/tool event counters unchanged across this activation and offline check;
  Exa control hash and Trench configuration/suggestion-dedupe source hashes equal.
- Both original partial Turns retain exact answer/request/metadata hashes.

Private receipts and runnable activation/offline/seal scripts are under
.artifacts/cloud-verification-defaults-01/ in the task worktree. No external
model/search request, original-Run mutation, Trench source change, push or remote
deployment was performed. Local Worker activation only; no page/model E2E.

## Real explanatory page Turn acceptance

One user-authorized new Turn, 2026-10-18, on the normal updated Worker:
conversation `conv_1792321396376_d5a89a`, Turn
`50e4165d-1762-4a88-a1cd-f728143ca0e0`, Run
`6bbb20ca-2f66-4127-abea-aba7cee90aed`. Question: 简要解释数据库中主键与外键的区别，并说明删除用户时需要注意哪些关联数据问题。

- Actual page submitted once; scoped database shows one Turn and one Run.
- Completed with task_type=answer, required_outcomes=[answer_present], no unmet
  acceptance requirements. No change/operate outcome or mutation evidence was
  required for this explanatory question. Answer 3,484 UTF-8 bytes.
- High reasoning, thinking enabled, transient_v2. Main Run has one model request
  and response, zero tools and retry_count=0; model latency 5,959 ms.
- Turn creation-to-completion 9,781 ms; started-to-completion 8,061 ms. These are
  backend Turn intervals, not browser first-text timing.
- Exactly one real DeepSeek Flash suggestion POST succeeded and was stored.
  A complete non-truncated refresh observation contained zero POSTs; actual
  snapshot returned identical persisted suggestions and full answer. All six
  suggestion labels are visible after refresh. No response interception.
- Actual Worker scripted safety regression rerun: 33 cases pass, including
  explicit change and operate, stale/missing proof and missing read capability.
  Both mutating-contract cases suspend rather than falsely complete or request
  another unsupported verification round. This is deterministic Worker-process
  evidence; no real mutation, missing-tool fault injection or separate live
  change/operate page Run was executed.
- Exact protected original partial Turn hashes, runtime receipts, Exa control
  and Trench configuration/dedupe source hashes unchanged. Global durable
  model-request/response counters increased by exactly one for this main Run;
  tool counters unchanged. Suggestions are independently observed over HTTP.

Receipts: private page/acceptance.json, snapshot.json, network.safe.json and
after-refresh.png under the task artifact directory. The initial observation
spanned a buffer eviction on the first refresh; a second refresh used fresh
cursors and complete buffers for the zero-POST assertion. No extra model call
was used to replace a sample. No automatic retry, code/config change or restart.
