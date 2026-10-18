# Recovery verification state repair

CLOUD-RECOVERY-VERIFICATION-03, 2026-10-18. Local source/Worker/API delivery;
no Desktop, Trench product changes, provider/search calls or historical rewrites.

## Smallest shared repair

The continuation metadata whitelist now retains mutation_resource_epochs,
mutation_resource_evidence, mutation_requires_global, read_fingerprint_epochs
and contract_verification_prompted. Existing post-mutation prompt flags,
verification evidence and verified epochs remain unchanged. Approval,
clarification and durable researcher joins share this producer. Verification
continues to use actual resource scope and fresh evidence, never a skipped hook.

Previously an A/B mutation followed by only a B read could freeze into scalar
mutation_epoch=verified_mutation_epoch and incorrectly verify A on recovery.
The same roundtrip now preserves the unresolved A scope. Prompt deduplication
also survives an exact continuation rather than requesting the same check again.

At the shared Worker continuation entry, a known mutation whose resource scope
is absent/empty/invalid (or whose epoch is malformed) suspends before any model
or tool dispatch. No attempt is made to infer lost resource identity from text
or scalar epochs. It retains partial/unverified delivery and counters, sets
retryable=false, and leaves existing durable results untouched. The pause reply
is a safe status notice, not republication of an unvalidated frozen candidate.
Old snapshots with no recorded mutation are not blanket-blocked. Lease,
authority, cancellation, identity and normal continuation dispatch stay in place.

## Capsule and researcher result fidelity

The API capsule producer uses the existing is_skipped_verification predicate on
both summary and metadata before flattening tests to text. Genuine pass/failure
summaries remain evidence. New explicit custom skipped summaries and the legacy
Noop sentinel are excluded without relying on keywords or model inference.

Old Capsule/Session Handoff model-facing views filter the legacy fixed sentinel
at the existing materialization, conversation-summary and handoff boundaries.
The original Capsule, envelope checksum and Event Store remain intact. An old
custom summary whose skipped flag was already lost cannot be safely identified
from prose; this slice does not guess its meaning.

Child terminal-summary reads include the child's own SESSION_SUSPENDED event.
Within the existing 3 KiB JSON-escaped canonical summary budget, paused results
carry suspended status/reason, delivery status/unmet items, then the existing
answer prefix. Full originals remain in the Event Store. Large task-goal/source
metadata is excluded so it cannot displace the answer. Completed/cancelled result
behavior and suspended-to-failed delegation settlement stay unchanged. No new
status enum, forced redelegation, engine choice or model repair round is added.

Producer and verifier use the same canonical summary. For rollout compatibility,
an already-frozen generic paused wakeup is accepted only after the existing
linked-child terminal proof and actual suspended/failed status match; arbitrary
summaries or wrong statuses still fail. No old wakeup command is rewritten.

## Validation and activation boundary

Red-first checks reproduced the three findings; focused deterministic checks
exercise complete/incomplete/global resource scope, dedupe, malformed legacy
states, all three continuation types without orchestrator calls, explicit and
legacy skipped, immutable legacy views, CJK summary budget and old wakeup proof.

Source full/targeted and exact-image offline checks are recorded in WORKLOG.
Worker derives from normal b8175274, not the concurrent diagnostic image. API
derives from its current asset-recovery image. Only relevant modules are overlaid;
API also receives the existing shared skipped predicate needed by the new imports.
No dependency installation/base pull, configuration or global proxy changes.

Normal Worker/API activation waits for the shared diagnostic owner's explicit
restored-and-released handoff and a same-container/no-active-lease preflight.
Environment, command, mounts and security/resource settings are preserved. Search
process/MCP session, Yahoo default, fast, cooldown/fallback remain untouched.
The two existing change/operate Run pages will be reloaded only; both original
protected partial Turn hashes and high/v2/dedupe are checked before/after.
Private receipts live under the task worktree .artifacts/cloud-recovery-verification-03/.


## Completed local acceptance

Final combined no-model regression:1846 passed/3 environment skips; focused
contracts29 passed. Ruff, Mypy8 source files, diff and exact-image offline checks
pass. Actual normal Worker/API repeat the same pure assertion checks successfully.
No new fixtures/framework/dependencies or unrelated test repairs were introduced.

Stage-I owner restored/released b8175274 with no more updates before activation.
Same-container/no-active-lease and environment/mount/command/security/resource
preflight gates passed. The API preflight initially rejected YAML !override null
being interpreted as a literal command argument; no API update happened then.
An explicit empty argv now preserves the original no-extra-argument command;
entrypoint/logging wrapper compares exactly before/after. Dynamic HostConfig
aggregate hashes are not an equality claim. No startup/logging configuration
or unrelated API modules were changed.

Normal Worker image recovery-verification-03 is
3eb51845262f792eb0d174c650488b83f3effc2e1f3c6964aaa19a8d4a7e91ef;
normal API image recovery-verification-03 is
acf4978d16def5fd22a4e85ebbe4eb41fa29bb1f1377ba43125e5b462c65fc47.
Both healthy/restart0. Search ID/image/start/restarts and Exa control are exact;
Yahoo/fast/cooldown/fallback, high/v2 and suggestion-dedupe sources are unchanged.

Authenticated existing change Run5c9afa1f and operate Run52ce78cc were reloaded
without response interception, Turn submission, regeneration, model/search or
history rewrite. Both still show 部分完成 and their unverified/paused notices;
no execution summary shows 执行中, DeepSeek Flash/high remain selected. Their
Session event-count maps match the original saved two-model/one-write samples.
The new recovery/capsule contracts are proven by offline checks; these retained
partial Runs are not mutated into artificial crash/recovery samples.

Global durable model/tool counters are identical across the post-handoff update
and page checks. Both protected older partial Turns have exact answer/request/
metadata hashes throughout this task, including while the unrelated diagnostic
batch ran. API/Worker source bytes match their recorded overlay paths. Receipt
acceptance.json and change/operate screenshots are under the task artifact root.
No claim of complete browser POST-window recording is made. Source23c95263
locally integrated to cloud-agent-trench; no push/remote deployment or Desktop/
Trench product/source changes. New Worker baseline was handed to the diagnostic
owner to prevent later rollback to b8175274.


## CLOUD-CLIENT-RECOVERY-04 — Client Effect and provider continuation

Client Effect previously omitted the whitelisted verification scopes and dedupe
state at freeze/recovery, and scanned accepted receipts without a consumed-attempt
boundary. Native provider continuation also treated an uncertain timeout or invalid
response as permission to send a second ordinary model request.

Changes are limited to the common runtime; Trench and Desktop are unchanged:

- Freeze the existing continuation metadata before the scheduled event reaches
  its eager durable sink, and in the normal waiting snapshot. The strict event
  schema adds an optional field excluded when absent; no migration or legacy
  payload rewrite. Lazy snapshot serialization runs only for deferred effects.
- Restore metadata in both provider-safe and rebased receipt branches. Merge
  the current action fingerprint with historical fingerprints; do not replace
  verification scope, read epochs or one-time verification prompt markers.
- Recover Client Effect through the existing active-continuation conflict gate.
  Persist its effect identity on the existing fenced completed-continuation
  start before entering the orchestrator. No duplicate generic start is emitted.
- Result boundaries consume prior receipts, including duplicate accepted commands.
  A fast receipt before its own waiting marker is still resumable. An old or new
  start without a durable result boundary suspends without invoking a model again.
  Missing legacy verification state also remains unverified, preserving counters
  and existing results; no inferred scope or automatic replay.
- Shared exception classification retains only whitelisted continuation state,
  including Client Effect, and withholds unrelated private metadata.
- Native continuation timeout, ValueError and rejected response suspend with
  retryable=false; cancellation and other errors propagate without fallback.
  Only NotImplementedError, now explicitly documented as pre-dispatch unsupported
  capability, permits ordinary fallback. Both tracked and untracked paths clear
  the in-memory reference after the attempt. Explicit invocation policy remains
  unchanged and continues to bypass this optional native path.

Validation: 109 offline focused tests pass across Client Effect, approval,
clarification, child wakeup, recovery verification, provider storage/reference,
context window and concurrent tool paths. Ruff and 14-source-file Mypy pass.
All model gateways in these checks are scripted/stubbed; no provider or search
requests. This proves safety behavior, not new model latency or search quality.

Local Worker-only activation and protected-Run checks pending. API/Search process,
MCP session/control state, Yahoo default/fast, high thinking/v2, original partial
Turns and Trench configuration must remain unchanged. No push/remote deployment.
