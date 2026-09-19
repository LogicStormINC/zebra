# Cloud Agent + Trench rollout and rollback runbook

This runbook closes `CLOUD-REMEDIATION-R14`. It does not turn a source build or
an HTTP 200 into production acceptance. G2 and G3 pass only when the immutable
candidate, real dependency results, browser result and rollback rehearsal all
refer to the same candidate digest.

## 1. Required artifacts

Create these outside Git under `.artifacts/cloud-evidence/`:

1. `release-manifest.json` from `make release-evidence` with status `PASS`.
2. A filled copy of `configs/cloud_rollout_candidate.example.json`.
3. `rollout-attestation.json` from `make validate-rollout-candidate`.
4. Raw evidence for every G2/G3 scenario, with no credentials or business data.
5. `rollout-rehearsal.json` and its machine-validated verdict.

The candidate pins full Zebra and Trench commits, content-addressed images,
database revisions, protocol read/write sets, config digests, capabilities and
the exact release-manifest file SHA-256. The resulting candidate SHA-256 is a
canonical JSON digest, so formatting changes do not create a different release.

Never put passwords, bearer tokens, HostGrants, database URLs, cookies or raw
business payloads in these artifacts.

## 2. Freeze and attest the candidate

Build images from clean worktrees and resolve registry digests after push. Do
not use mutable tags as release coordinates. Hash the rendered, secret-free
configuration rather than the `.env` file containing secrets.

```bash
sha256sum .artifacts/cloud-evidence/release-manifest.json
make validate-rollout-candidate \
  ROLLOUT_CANDIDATE=.artifacts/cloud-evidence/rollout-candidate.json \
  RELEASE_MANIFEST=.artifacts/cloud-evidence/release-manifest.json
```

The validator fails unless the release manifest is `PASS`, its Zebra SHA is the
candidate SHA, all images are digest pinned, database rollback remains
forward-compatible, write protocol versions remain readable, and the rollout
is exactly internal `0%`, canary `5%`, then full `100%`.

## 3. Deployment order

1. Stop promotion and new task admission if the current evidence is stale.
2. Take PostgreSQL and object-store backups and record independent read-back
   evidence. A file merely existing is not a successful backup.
3. Apply additive database migrations and deploy readers that understand old
   and new Host Manifest and Workspace Snapshot versions.
4. Deploy the pinned Zebra control plane and Worker images with new writes and
   optional capabilities disabled.
5. Deploy pinned Trench API/frontend images. Keep Client Actions disabled.
6. Run G2 in the isolated internal namespace.
7. Enable each of Client Actions, Host writes and external memory separately.
8. Promote only after the previous phase's evidence validates.

No step may widen a namespace, tool profile, egress route or browser authority
to make a failing test pass.

## 4. G2 system-closure evidence

Each passing scenario needs a non-empty `evidence_ref` pointing to a bounded
report, trace or test artifact. Redact identities and payloads while retaining
the candidate digest, revision, terminal status and business receipt state.

| Scenario ID | Required assertion |
|---|---|
| `postgres-recovery` | Durable task/event state survives restart and replays once. |
| `object-store-roundtrip` | Versioned object is written, read and digest matched. |
| `message-wakeup` | One durable wakeup reaches the intended task. |
| `trench-browser-client-action` | Real browser executes only the bound Surface/action/revision. |
| `worker-crash-recovery` | New Worker resumes; fenced Worker cannot commit. |
| `duplicate-delivery` | Repeated message/effect yields one business result. |
| `timeout-recovery` | Unknown write reconciles by receipt; it is not blindly replayed. |
| `authority-revocation` | Revoked or expired authority fails closed. |
| `page-disconnect` | Refresh/disconnect cannot revive an in-flight action. |
| `scheduler-wakeup` | Repeated firing produces one side effect. |
| `memory-delete` | Deleted memory is not recalled and cleanup is recorded. |
| `gvisor-execution-cleanup` | Target engine uses `runsc`; process/workspace cleanup is proved. |

`memory-delete` may be `NOT_ENABLED` only when `redis_agent_memory` is disabled
in the candidate. Browser and gVisor scenarios follow the same capability rule.
An optional capability cannot be enabled by configuration until its scenario
passes.

## 5. Phase promotion hard gates

For internal, canary and full phases record the exact traffic percentage, at
least one real sample, and these fixed correctness counters:

- `authorization_errors`
- `duplicate_effects`
- `unresolved_mutations`
- `lost_wakeups`

All four must be zero. Performance is compared with the named R13 workload; it
is not a capacity promise. Any correctness failure stops promotion immediately.

Canary traffic is limited by an explicit namespace allow-list. Do not implement
canary by randomly accepting five percent of otherwise unauthorized requests.

## 6. G3 rollback rehearsal

The same candidate must prove:

| Scenario ID | Required assertion |
|---|---|
| `backup-restore` | PostgreSQL, object versions, scope metadata and deletion ledger read back and replay-match. |
| `forward-migration` | Old data remains readable after additive migration. |
| `old-protocol-compatibility` | New reader accepts frozen old tasks; old Worker never guesses new tasks. |
| `feature-disable` | New writes/actions/memory can be disabled independently. |
| `application-rollback` | Previous digest-pinned apps run against the forward-compatible schema. |

Rollback order is: stop admission, disable the affected capability, drain or
pause tasks using a protocol unknown to the old Worker, reconcile uncertain
Host writes, then restore the previous application images. Never automatically
down-migrate the database. Real business effects and completed memory deletion
are not reversed by application rollback.

## 7. Rehearsal verdict

Create `rollout-rehearsal.json` with schema
`zebra.cloud-rollout-rehearsal.v1`, the attested `candidate_sha256`, an
environment name, the three phase records, and exactly the scenario IDs above.
Then run:

```bash
make validate-rollout-rehearsal \
  ROLLOUT_CANDIDATE=.artifacts/cloud-evidence/rollout-candidate.json \
  ROLLOUT_REHEARSAL=.artifacts/cloud-evidence/rollout-rehearsal.json
```

Only a `PASS` verdict plus review of the referenced raw evidence closes G2/G3.
Missing, duplicate, failed or capability-inconsistent scenarios fail closed.

## 8. Current target status (2026-09-20)

The target `192.168.110.30` accepts a TCP connection on port 22, but repeated
SSH probes either time out during banner exchange or are closed before
authentication. `http://192.168.110.30:18080/health` either times out or returns
an empty reply. This is a host/service availability blocker before
authentication, not evidence of an account-password failure.

Therefore the implementation and local validators can be reviewed, but the
real Trench browser, target gVisor and production rollback scenarios remain
unexecuted. Keep R07 and R14 open until the host responds and these artifacts
are produced from one immutable candidate.
