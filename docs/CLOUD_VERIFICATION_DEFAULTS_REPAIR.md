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

## Real mutation-page attempt: stopped, not accepted

User authorized real change/operate page scenarios with isolated state and no
automatic retry. Two unique markers were registered before activation. A
temporary derived Worker image scoped fixture tools/contracts/budgets to only
those markers; normal policy, fencing, Effect dispatch, provider/high/v2 and
finalization remained in place. API/Search/Trench product logic was untouched.
The write tool can only exclusively create its fixed temporary state file;
strict enum arguments reject out-of-scope data. No postcondition evidence is
fabricated. Offline checks exercised real isolated file I/O.

The first change sample is retained as a failure, not replaced:
conversation conv_1792322144198_f4e84b, Turn
8dc3f2b1-afb5-4430-9154-78e50d2c5a07, Run
2460072e-415c-4e48-91ef-e0246d0e48ef, canonical Session
9befd112-8439-4fd4-a16c-1120c7a9114b. Page status failed, high/transient_v2,
17.400s Turn interval. Three model rounds, each retry_count0; one tool attempt,
zero successful tools, no suggestion generation. The third model round was
a quality revision after missing evidence, not a post-success verification
round. Required verification was true, but this run did not reach its intended
successful-write/missing-proof checkpoint.

Durable Effect evidence is failed_no_effect/payload_not_admitted, no result and
no retained claim epoch. The failure occurred about2.03s after scheduling; the
fixture state file was absent. This proves failure before business dispatch,
not a verified mutation or the target no-extra-round guarantee. The operate
sample was never started under the stop-on-error protocol. No model retry,
replacement sample or success claim followed.

Read-only diagnosis found acceptance setup defects: an unconditional .pth import
loaded the whole Worker in Artifact reader Python children, and a proxy around
FencedEffectToolGateway changed isinstance checks used for terminal observers.
A prepared, inactive test-image revision restricts startup injection to the
Worker CLI and retains the original fenced-gateway object/type. Offline cold
child comparison (three samples each): failed fixture1.785/1.915/1.891s with
fixture loaded; corrected fixture0.102/0.100/0.066s with fixture absent; normal
image0.096/0.091/0.070s. This overhead can consume the observed2s admission
window; no production-root-cause or live repaired-Effect claim is made without
a successful targeted observation. Corrected isolated-I/O boundary checks pass.

Normal Worker87505c5e was restored healthy/restart0; fixture absent, actual Worker
33offline checks pass. API/Search runtime, Exa control, Trench configuration and
dedupe hashes, and both original partial Turn full hashes remain unchanged.
Both activation preflights compared environment/command/entrypoint/mount/network/
security/resource settings explicitly; the broad HostConfig diagnostic hash
differs, so whole-hash identity is not claimed.

Private live-mutations/ receipts include frozen protocols/hooks, cold-child
comparison, acceptance-blocked.json, canonical public events and change-page.png.
A fresh bounded pair requires additional user authorization after this stop;
the failed Run stays retained and is never replayed.
