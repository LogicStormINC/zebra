# Native Task admission proof (2026-10-11)

## Scope

COV-EXEC-01, Luke Ding/Codex, `codex/cov-exec-01` isolated worktree. This
follow-up was claimed before coding. It replaces normal repeated Task descriptor
replay and whole-Session count/min/max with a native incremental proof; it does
not cache current Task bindings, Host grants, lease authority or permission.

## Contract

Migration89 maintains one `coverage_task_summary` per deployment/Session inside
the Event transaction. Starting at sequence0, each insertion must be exactly
last+1. The first strict TaskPrepared pins its complete native origin; later
TaskPrepared payloads must match exactly. Non-admitted or changed descriptors,
sequence gaps and any historical update/delete invalidate the root. Truncate
invalidates all roots if not already refused by independent append-only guards.
Roots cannot be inserted/edited/deleted/truncated directly through ordinary DML;
invalidated roots cannot be reset. Scope moves invalidate both Sessions.

New normal final_certification reads check migration checksum, summary origin,
stream version and Task cardinality through one indexed query. They then read
the latest binding snapshot freshly and validate typed admission, identity,
Host context, history and contract. Frozen grant/revocation/clock/fence guards
remain separate and unchanged. Native admission and stream continuity are not
count-only claims: per-append continuity plus unique native sequence establish
the complete prefix, with exact descriptor matching at insertion.

Only normal budget index, qualified receipt policy and incremental commit
verification use this proof. Full initialization, recovery, eager reads and
independent publication/certificate read paths retain complete native replay.
No final certifying path accepts this summary as its authority. The policy
already proven in the same locked budget phase is forwarded into preflight;
it is not retained across phases or external callbacks.

Existing Sessions are seeded invalidated, not backfilled from mutable indexes.
Unsupported or repaired history retains legacy independent scans. Changed
payloads may conservatively disable the fast path even when effective admission
is unchanged; never silently bless them. Legacy requalification is still OPEN.
Current runtime DML is the boundary: privileged DDL/trigger disabling is outside
it. Restricted runtime DB roles are a production rollout prerequisite, not a
superuser-tamper guarantee. Fleet continuation digest includes Task-summary/89
and rejects consumers qualified only for v87 or v88.

## Validation

First four native roots passed30.48s: bounded proof versus independent replay;
mutation/rollback/direct-edit guard; changed stream/missing current binding;
missing migration fallback. Initial test attempt called an indirect fixture as
a function; corrected without production edits. Existing append-only receipt
descendants reject cascading Event truncate; regression preserves that refusal.

Expanded checks add1,000 actual native TaskPrepared appends: normal policy reads
remain two queries without selecting session_events, match independent replay
and reject foreign deployment. Existing-history migration stays invalidated;
projection repair never requalifies; conflicting descriptor/gap refuse.
Expanded root8 passed57.31s; separate current-binding renewal1 passed9.92s.
Renewal is committed by another connection between two normal reads: new digest
is visible immediately and the old MODEL budget refuses the changed policy.
Final native MODEL matrix54 passed299.54s; Worker/fleet82 passed252.27s, zero
skips. Those matrices ran in separate scratch schemas concurrently, so their
durations are not performance evidence. Serial-nine results follow separately.

Serial native nine1 passed61.53s, `/tmp/cov-task-summary-nine.xml`: after fixture
setup/first handoff through independent certified completion56.0948309s,
49137execute/2413binding reads/518GET/10callbacks/18qualified/zero exceptional
full recovery/two MODEL initialization replays. Prior same-callback v88 result
52.1280589s/49237execute has equal bindings/GET;100 executes removed, but this
run is slower. No overall latency gain or SLO claimed. Task history growth is
bounded independently by the1,000-append regression, not by this tiny workload.
Trigger-internal SQL/cursor/implicit transactions are excluded from execute
counts. Business30795execute24.5527s/reset11904/clock4847/timeout-config1591.
Inclusive Artifact record837calls14.7332s, commit18calls6.0747s, continuation
27calls2.3737s, publication2calls4.7440s overlap and must not be summed.
Native PG/Worker, controlled Host/model/S3; no real tenant or semantic claim.

Pure policy/verifier/recovery/readiness66 passed1.34s,4 native environment skips.
Two policy-forwarding fake tests failed because their partial fake binding did
not implement the previously introduced v88 native MODEL index. Their mocked
index now verifies the forwarded exact policy; native integrity is tested by
the independent native matrix, not these fake tests. No production gate changed.
Final static gate passed1098 source files/eval30; actual tracked+untracked2578
file-size and git diff checks passed after the final renewal regression.

## Remaining

Normal proof for a Task descriptor is now bounded, not the whole invocation:
per-Artifact fresh Host/Task lineage still fans out; MODEL source volume and
manifest membership still scan; object-proof transactions and historical
qualification require follow-up. Tenant concurrency/history-growth SLO, live
mixed-fleet rollout and real semantic accuracy are not established. No labelled
business dataset was supplied. Production receipts remain OFF. No business
migration, primary checkout edit, restart, activation, merge, push or deployment.
