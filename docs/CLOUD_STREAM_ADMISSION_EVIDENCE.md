# CLOUD-STREAM-ADMISSION-01 bounded component evidence

Date2026-10-13; Luke Ding owner/Codex executor; branchcodex/cloud-stream-admission-01,
base0d49f0b0. The12Oct freeze was withdrawn13Oct after SPEC NO-GO; repairs are accepted after renewed
independent SPEC and QUALITY GO; local integration pending.
User authorized validated local stages into cloud-agent-trench; no push/deploy.
This document establishes component evidence; full product gates remain OPEN.

## Implemented boundary

- AG-UI streamCapabilities become typed stream_capabilities in SessionCommand
  intent and its fingerprint. Optional server stream_admission is outer accepted
  v2 Event metadata, atomically written by the existing append. Legacy is pinned
  by absence; exclude_if prevents generic Event normalization inserting null.
  Same-key retry
  returns the original metadata after the new-admission flag changes; different
  requested capabilities conflict. Client-owned mode metadata is rejected.
- New v2 requires explicit cloud flag, actual VerifiedHostGrant and every v2
  capability. Source-qualified Task privacy must explicitly be ordinary and
  the active Segment must match. Missing capabilities/internal unsigned callers
  remain legacy; coverage cannot select temporary drafts. Defaults are off.
- No new schema/index/dependency. Trusted loader reads the unique canonical Run
  anchor and exactly one bounded source row, verifies accepted intent integrity
  and metadata Task/Run/capabilities. Source faults/corruption cannot imply legacy.
  Missing old metadata remains legacy, including256-character historical Run IDs.
  New incompatible >128-character v2 IDs reject without changing old legacy IDs.
- Actual Worker loop always composes a mode-aware factory for cloud execution.
  Host binding loader no longer depends on optional memory availability.
  Frozen v2 is honored when admission turns off; absent/broken Redis suppresses
  drafts while full response/facts retain their original canonical sink/authority.
- Callback hook is the existing actual HarnessModelStep hook following durable
  request persistence. A timer can advance the frontier between append and hook:
  seek <=256 scalar headers backwards under cumulative2s; pass only proven
  ancillary HARNESS public_expression on the same Segment/Attempt with a distinct
  ID. Hydrate only inspected request rows within cumulative1MiB. Verify current
  callback/model_call/Attempt/Segment/actor/purpose; never scan old response bodies.
- Actual current_turn is read from bounded native authority evidence (<=2048
  relevant Events/1MiB/2s). No synthetic Turn UUID; legacy derived textual IDs,
  closed/missing/later Turns fail closed. Fresh native lineage resolves root
  binding on a child Segment. Scope is the canonical active Segment singleton.
- Initial factory proves accepted metadata plus exact progress Run anchor once.
  Accepted Events are append-only: only this immutable admission is cached.
  Every issue/activation still reads current source Task/privacy/Run/exact anchor,
  callback suffix, full lease, fresh persisted API-verified Host binding and Turn.
  No caching of mutable grants/privacy/Run/fence; no per-frame PostgreSQL.
- require_task_host_context fences exact stored principal/workspace/thread/Run,
  authority issuer and opaque namespace; expiry is clipped to persisted grant,
  fresh lease and30s. Worker never manufactures VerifiedHostGrant from JSON.
  External revocation not yet reflected in a stored binding is not instant:
  bounded authority expiry remains the honest current boundary.

## Executed checks

Disposable local PostgreSQL17/Redis8 only. Private baseline environment is
sourced by path; no secrets/env in commit. Native checks create unique databases,
schemas/namespaces and key prefixes and delete only their owned data.

- Final configured affected regression261pass/no skips/no warnings76.92s. Covers typed
  contracts/settings, original legacy/AG-UI command/extension routes, real signed
  Host HTTP guards, storage root-binding/hand-off reads, original Writer fencing,
  Worker loop, public output deadlines and Redis adapter checks.
- Supplemental legacy SessionCommand/Turn compatibility19pass0.43s.
- Final regression includes16 native composition cases: immutable metadata retry;
  actual model hook; canonical Turn; old >1MiB response outside new Run;
  intervening timer fact; forbid rereading proven immutable admission;
  expiry/Run-target/Turn/Redis/source/fence faults; actual hand-off root binding;
  changed current exact anchor rejected at BOTH issue and activation resolve;
  corrupted fresh digest vs valid API renewal; actual PublicExpression before and
  after activation; new main/unknown/forged/same-ID supersession; legacy old-worker
  parser/fingerprint compatibility for disabled/unsigned/coverage/capability-free
  requests and typed legacy metadata reader compatibility.
- Actual cloud loop composition + command recovery15pass/no skips6.91s proves
  mode factory and binding loader are wired without optional memory.
- make check GO: file-size2999/zero violations, Ruff, mypy1257sources, eval30/30.
  Existing settings.py reaches its500-line hard limit; new options belong in the
  focused stream_settings.py rather than growing that existing module.

Artifacts (untracked): .artifacts/admission-regression-repaired.{log,xml},
admission-native-final.{log,xml} under .artifacts, admission-check-repaired.log,
admission-core-compat.log, admission-loop.log and admission-anchor.log.
Run pytest with --tb=short and -o junit_family=legacy for cost properties.
Private environment paths/values must never be printed or staged.

## Fixed-cost SQL and latency evidence

Measurements use actual source metadata, native lease/Turn and persisted Host
binding, rather than the earlier Writer synthetic admission/Grant tables.
Two actual HarnessModelStep invocations emitted10 and100 coalesced frames.
The second invocation follows a large historical response and a timer race.

| Local client SQL / measured scope | Before immutable cache | Frozen component |
|---|---:|---:|
| Two callback activation scopes |258|162 (81/call)|
| Provider callback text scopes,10+100frames |0|0|
| Two measured request/response scopes, including activation/facts |626|530|
| Activation seconds for two calls |0.4394,0.4480|0.3766,0.4024|

Activation scope starts immediately before writer.start_public_call and ends
when it returns; timer fact is outside activation but inside measured total.
Callback text scope starts in the stub provider loop AFTER activation and ends
after its10/100 callbacks. Count client SQL including adapter connection health
checks; no claim about isolated server trigger statements or cluster-global WAL.
Initial Task/bootstrap/command admission and factory initial-mode read, HTTP,
real provider/network time, SDK/render and30s renewal are outside this sample.
The native fault probes preserve canonical sink invocation; a lost fence still
rejects unauthorized durable writes under the existing authority checks.

The remaining81SQL/~0.3–0.4s activation cost is material. Zero frame SQL alone does
not establish80–95% TOTAL SQL reduction, invocation TTFT or100-subscriber SLO;
short low-frame Runs can regress. No50ms performance gate is asserted here.

## Remaining product gates

CLIENT three SSE paths, signed cursor/resume, SDK draft label/replace/reset;
aggregate quotas/GC/reliable hints; full matched Worker+signedHTTP/Host+SDK/browser
paired SQL and latency; provider cancellation/STOP/failure/rollback; real business
host and deployment remain separate OPEN gates. New v2 admission stays off until
those prerequisites pass. Old Workers cannot consume new outer v2 metadata:
rollback requires stopping new admissions while capable workers drain frozen v2.

Refrozen source/config/test manifest:17files, combined SHA256 d1066f670c1d630f4a497de084b0ab6f5ef4a47b2d6cde9696fb3276866a997f.

## 2026-10-13 review repairs accepted

Independent native review found three gaps: fresh Host snapshot/context digest
self-validation, old callback renewal after a different ordinary request, and
actual ancillary PublicExpression interleaving. Both fresh snapshot self-proof
and initial frozen identity are now checked; only trusted distinct ancillary
HARNESS requests on the same Segment/Attempt may be passed by the locator.
Later ordinary/unknown/forged/same-ID requests invalidate old renewal/resolve.
Cumulative hydrated request rows stay <=1MiB/256 header positions/2s; historical
response bodies remain excluded. The previous frozen hash is withdrawn.
Compatibility review also found generic Event normalization inserting null;
legacy omission is now guaranteed by the accepted model field serializer.
An earlier255pass/1 malformed-source fixture projection failure was corrected
and the final261-case run passed. Independent renewed SPEC GO39/no skips35.4s;
QUALITY GO39/no skips34.81s plus original Writer26/no skips6.48s. All17frozen
source/config/test hashes match. Accepted bounded component for local integration;
full performance/CLIENT/reliability/rollout gates remain OPEN.
