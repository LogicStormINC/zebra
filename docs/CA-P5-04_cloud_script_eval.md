# CA-P5-04: cloud script Eval resources and shared quota backing

BC Runtime/Eval; implemented precursor to Overdoze's actual P5 gVisor S1. The
existing evaluator could run its Seatbelt development proof, but its cloud OCI
factory omitted the required fenced instance collaborator. A no-I/O reproduction
confirmed the failure. Production script temporary directories also require the
configured shared quota backing, rather than an arbitrary local `/tmp` directory.

## Ownership and execution

Reuse the existing trusted Eval approval, exact operation UUID, Suite/digest,
materialized Version and actual script-grading producer. New cloud OCI claims take
a shared namespace admission lock and require open admission before atomically
persisting their original and a separate cloud hold. Existing original claims
remain original observations, including when admission subsequently closes; they
never rerun or acquire a new original ID.

The Eval original owns dedicated ephemeral sandbox records through the existing
`RuntimeInstanceLifecycle` protocol. These are not business Tasks or fabricated
Worker leases. Reserve one exact instance/spec/pinned-engine identity before create;
record full CID separately; require current publisher approval, unchanged active
original and exact ownership before execution. Late create/removal observations
remain recordable after approval revocation but cannot grant execution. Keep an
append-only immutable resource event log; no namespace scan or automatic takeover.
At most64 retained resources per Eval original; original claim capacity remains
1024 attempts per Version. Increasing either requires an explicit archive design.

Only the live stack that won the original claim executes. A crash, missing create
ACK, missing resource settlement or lost Eval result remains unknown. No background
resend, unbounded cleanup scan, retry with a new UUID, business Task replay or
Controller acquisition is supplied. Existing exact OCI metadata checks and removal
observations apply. Resource settlement alone does not complete an Eval or create
passing evidence. The producer grades actual outputs, then atomically commits its
original result/evidence only after all of its tracked resources have settled.

## Safe lifecycle proof

A cloud Eval hold remains active until its Eval original is completed. Native
Runtime gate current/original observations and open/assess requests fail unavailable
while such a hold exists. They must not manufacture a quiescent observation from
only business Task/lease tables while an independent Eval can still dispatch.
Explicit drain remains allowed and fences new cloud Eval claims. Existing Eval
work may settle under its original authority; lifecycle readiness remains unavailable
until completion. Unknown continues to block, even if its resource appears absent.

The Runtime gates v1 JSON/contract digest and worker compatibility algorithm remain
unchanged. A503 is absence of current proof, never stop/activation/non-commit
permission. The Go consumer already rejects unavailable current source. Existing
installations without this optional cloud Eval schema retain old behavior because
they cannot dispatch this new cloud Eval profile. Drain old supported writers
before activating the new evaluator/source combination; raw Docker/DB/host mutation
is outside this authority boundary.

## Workspace and historical compatibility

`ScopedNativeScriptRunner` accepts an optional trusted workspace parent. Cloud
composition uses `ZEBRA_WORKSPACE_VOLUME_ROOT`, creates only an empty owned child,
and mounts that child read-only with no business workspace/network access. Factory
validation checks containment and the actual declared backing mount/quota. The
runtime class/image/limits/spec and exact instance collaborator still apply.
Seatbelt/local callers keep their existing defaults. Without a declared root,
existing quota validation keeps its prior workspace-root behavior; it is not relaxed.

No new settings or historical Bundle fingerprint fields are introduced. The existing
workspace-volume environment declaration is reused, and Overdoze seals its physical
binding in approved descriptors. Old task snapshots, public Bundle/Definition/Task
contracts, capability/script assets, Eval originals, Event/Effect history and Coverage
are retained. No model TLS bypass or task/cancellation semantics change.

## Explicit initialization and validation

Operator-only `python -m zebra_agent_worker.script_evaluation --mode initialize ...`
adds cloud hold/resource/event tables and the immutable-event trigger together with
the existing Eval schema. API/Worker startup performs no new DDL. Ensure service
roles have appropriate access before activation; do not run production migration as
part of acceptance. No business/event/lease history is rewritten or deleted.

Targeted real PostgreSQL and pure factory regressions cover closed-admission refusal
before claim, original holds making Runtime observations unavailable, explicit drain,
exact-engine/CID/spec ownership, current revocation, late resource facts, pending
resource completion refusal, negative evidence settlement, no fabricated Task lease,
and shared quota containment. Existing actual Seatbelt Eval and script binding
regressions also pass. These tests do not claim actual gVisor execution; owned S1 must
run the source-pinned cloud API/Worker and evaluator before parent P5 closes.

Full gate outcomes are recorded under `docs/evidence/ca-p5-04/` after successful
command exits. No production deployment/migration, main merge, business BFF/SDK
credential change or production HA claim is made.

Fresh full gates: make test11209 passed/3067 conditional skips; make check passed.
[Validation receipt](evidence/ca-p5-04/validation.json). Actual cloud gVisor remains07C.
