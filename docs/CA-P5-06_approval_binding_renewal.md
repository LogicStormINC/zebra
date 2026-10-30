# CA-P5-06 — Approval command binding renewal

## Problem and boundary

The trusted Go BFF exchanges a current HostGrant for each approval submission.
Native approval POST previously authorized that grant but never renewed the stored
Task binding. Its approval-resume command could therefore inherit the adoption-era
binding expiry. This is a missing Native admission step, not evidence that BFF
must retain credentials in the browser or increase the 30-second delegation cap.

This slice reuses `renew_host_binding_for_command`; it adds no Go API, migration,
credential store, Worker protocol, automatic retry or Controller acquisition.
Credentials stay in BFF. Historical bindings, original operation receipts,
unknowns and Coverage evidence remain unchanged.

## Ordering and partial outcomes

1. Validate input and current Task/Run, client session, Profile and Controller.
2. Inside the existing four-second I/O deadline, renew using the verified grant.
3. Enter the existing approval stream transaction, recheck current authorization,
   then read or commit the original decision/resume receipt atomically.
4. Original GET remains read-only and never renews authority or submits execution.

Renewal intentionally occurs outside the approval transaction lock, as it uses
its own PostgreSQL connection and CAS. Invalid authority, missing binding, CAS
conflict or unavailable storage prevents approval writes. A successful renewal
followed by approval failure may leave a new binding revision without a decision;
this is current authority, not proof that approval or execution committed. GET
of the original operation remains the reconciliation mechanism. An absent receipt
is not a non-commit proof and does not authorize automatic resubmission.

Current authorization is checked before renewal and again under the approval
lock. An earlier proposal renewed before authorization; deterministic regression
checks failed on that ordering. No failed Controller request may mutate binding.
Frozen identity, issuer, policy, resources, capability and technical ceilings are
still enforced by the shared helper. Successful renewal is not a guarantee that
a short-lived grant remains current when a later Worker boundary is reached.

## Evidence and remaining acceptance

- Red ordering regression: four failures and one pass before the ordering fix.
- Focused API/helper/approval suite: 28 passed, four PostgreSQL-dependent skips.
- Dedicated disposable PostgreSQL: four passed, including fresh binding revision
  persisted before approval lock, frozen ceilings, decision/resume and original
  GET with no additional binding or event mutation. This suite stubs current
  session authorization explicitly; the separate API tests cover denial ordering.
- Explicit serial resume: Native make test11216 passed/3068 conditional skips;
  make check1447 typed sources/30eval passed. Overdoze30 race packages and Worker
  receipt selfcheck passed; make check passed with74 inherited Biome warnings.
- Container/network identities match the baseline;23 new anonymous volumes from
  the Native test window remain under ownership review. Do not delete unproven data. No owned
  heavy test process or temporary service remains; prior interrupted gates are
  retained as incomplete and do not contribute to these successful results.
- Actual source-pinned BFF/SDK/approval/Worker S1 remains a separate acceptance.
  These tests do not establish cloud rollout, fleet HA or complete P5 acceptance.

No production deployment, production migration or mainline merge is performed.

## Inherited temporary-volume cleanup finding

Native fixtures still use `docker rm -f` in five shared PostgreSQL generators
and the explicit conformance shell. They can leave anonymous image volumes.
All23 new anonymous volumes were created in the Native test window; no new Go
volumes remain. The daemon retains only256 events, so historical mount ownership
cannot yet be reconstructed for every volume. They are unreferenced and retained
in a precise metadata manifest pending proof, not removed on temporal correlation
alone. Fix shared fixture teardown in a separate operations task before further
heavy Native acceptance. This does not invalidate either completed code gate.
