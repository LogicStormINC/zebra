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
