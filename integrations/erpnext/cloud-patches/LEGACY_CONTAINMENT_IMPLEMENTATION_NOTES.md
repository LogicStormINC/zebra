# ERP legacy workspace containment — source review only

This slice is based exclusively on captured schema105 source and the pinned API
`2156443eea6ad9330853d16ece204dfa0995a41e5b5b677063386216797daaef` / Worker
`33b93abc4b257d0639730f2e2c388d765f092d7979a03b117f6387b0049c0e18` images.
It adds no migration, dependency, allocator, mount hook or model call. It does not
activate a service, replay a Task or copy the shared workspace. Existing followup
patches remain present; the old freeze manifests describe their historical stage,
while `legacy-slice-sha256.json` freezes the current combined overlay.

## Policy and deliberately closed boundary

`ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT` accepts `disabled` (default) or `enabled`.
Enabled with any deployment namespace other than exactly `erpnext` is an error.
Execution/memory startup requires the explicit native policy; execution also
requires its native binding-loader wiring. Cloud composition creates one native
workspace control store shared with the resolver; the policy never discovers the
control store through resolver/provisioner private attributes. The new store
`get_in_transaction` read reuses the existing native row decoder.

The native policy reads Task -> current active Segment -> Workspace projection ->
control UUID and the existing typed latest binding/lineage reader in one snapshot.
It recognizes only `host_reference` source locators exactly equal to
`erpnext://private-workspace/v1/<canonical Host thread UUID>/<workspace_ref>`.
The Host binding must validate exactly one thread/principal, the stored context
digest, ERP issuer `https://erpnext.zebra.local`, ERP host app/namespace,
`erp-u-` plus40 lowercase hex, and no contradictory non-NULL control owner. Native API admission leaves that
owner NULL; it is not positive ownership evidence. The full native join and
typed binding/source comparison provide the classification evidence. Origin
remains part of the existing typed bound-context digest; it is not assumed equal
to the authority issuer.
The projection accepts the two existing resolver spellings `workspace://UUID`
and `workspace:/UUID` because native `Path` bootstrap folds the double slash.
Source locator URI folding, raw paths, missing facts, drift and unknown sources
are never a private-generation proof.

Classification is NOT execution admission. Legacy/unknown/malformed facts refuse
with `legacy_observation_only`. Even a valid private generation refuses with
`private_workspace_not_activated`: real per-workspace quota/mount enforcement
(Worker UID65532) and fresh authorization hooks do not exist in this slice.
No boolean can activate a private generation here. Consequently enabled ERP
ready and memory SQL readers add `AND FALSE` before `LIMIT`: no generation is yet
eligible, and neither old nor private rows cause repeated claims or batch starvation.
This predicate must change only with actual generation admission hooks.

## Traced callers and placement

* Modern broker/fallback both call `handoff_command`, then
  `execute_claimed_session` -> `execute_existing_lease` -> heartbeat -> stale retry
  -> `_execute_claimed_session_once`. Legacy/ready/direct execution calls
  `execute_session` -> `execute_session_with_lease` -> the same heartbeat/retry seam.
  The final source check is after committed-completion reconciliation and before
  progress preparation, attachment reads, context materialization, workspace
  resolve/provision/reset, model factory, generic/files/analysis/skills/MCP tools.
  Stale retry re-enters that seam. It raises a distinct `ERPWorkspacePolicyRefusal`,
  never `WorkerExecutionError`, so setup finalization cannot synthesize a failed
  Attempt/Started/handled receipt under a fresh recovery fence. Real heartbeat
  cleanup releases the lease; ready callers catch the typed refusal. Broker's
  existing exception path already logs and cleans up claimed execution failures.
* Formal `handoff_command` detects enabled containment before candidate preparation.
  Because every generation is refused in this slice, it skips
  `prepare_command_candidate`, `prepare_command_handoff` and
  `prepared_recovery_connection` entirely. The native coverage preparation chain
  can otherwise call `NativeCoverageRecoveryCheck.prepare/_prepare` ->
  `verify_cloud_coverage_recovery`, reading Artifact bytes, Host manifests and
  descriptors and official model policy before reaching the later source guard.
  This was a real pre-policy escape found by independent QUALITY review; a harmless
  mocked preparation result did not test that path. Disabled containment retains
  the original candidate -> security -> coverage preparation ordering.
* Native SQL security checks `reject_missing_command_consumer` and
  `pin_command_consumer` remain in their original positions. Their complete chain
  uses native SQL and typed admission checks, not Host/model/Artifact I/O. Formal
  handoff retains pending scope, rollout eligibility, lease serialization,
  re-read pending, exact outbox/canonical validation, generation, retirement, Inbox
  and receipt identity checks before typed refusal. Qualified strict consumers are
  re-pinned with locked Task authority and clock-checked after tentative refusal
  metadata writes; expiry raises to roll back the transaction. Control kinds are
  unsupported by this execution-handoff function and retain the original dedicated
  STOP/CANCEL consumer path.
* The independent `prepare_command_candidate(message_only=True)` guard remains for
  other callers: native candidate/scope/outbox/generation validation and lease
  serialization precede its early no-preparation return. Formal handoff opens the
  native policy read-only repeatable-read snapshot while the lease boundary remains
  locked, then returns `REQUIRES_RECONCILIATION`, which existing consumers ACK.
  Denial is never represented as PREPARING. Only exact pending metadata is set to
  `dead` plus the typed policy code; no Inbox/Attempt/handled receipt is invented.
  Existing handled commands remain duplicate no-ops; an active lease, Started
  receipt or terminal control state prevents pending metadata overwrite. Receipt
  history remains intact. Outcome reads expose typed policy codes before generic
  reconciliation/delivery errors, after existing historical handled/terminal checks.
* Legacy `consume_once` validates the accepted command before policy. RUN/RESUME/
  MESSAGE refuse before append/claim, using the existing exact Event fingerprint
  rejection receipt, HTTP409. It does not call `fail_rejected_continuation` or write
  TURN_FAILED. STOP/CANCEL retain their original branches.
* Independent `CloudMemoryFinalizationRecovery.recover` checks immediately inside
  the claimed heartbeat before recorder/finalize/title reservation/factory and
  writes no fake memory completion receipt. The SQL memory reader excludes every
  unactivated generation before its oldest-first limit; the direct guard remains.

## Checks and evidence limits

`tests/check_legacy_containment.py` is a single runnable assert check over installed
native dependencies via existing `overlay_imports.py`; no framework or fixtures.
It exercises generation/ownership drift, legacy lifecycle/raw paths, both native
projection URI spellings, real heartbeat release through both execution entrypoints,
stale retry, zero input/setup preparation, independent memory refusal, legacy
409/idempotency/STOP/CANCEL, SQL predicate placement, modern prelude zero preparation,
idempotent pending refusal and active/Started/handled/terminal preservation.
The strict preparation regression supplies an actual `NativeCoverageRecoveryCheck`
with its original `prepare/_prepare` chain. Enabled handoff calls candidate/prepare,
Host authority/manifest/descriptor, model policy and Artifact read boundaries zero
times. Disabled handoff enters its real native preparation database boundary in
original order and stops at a fail-fast sentinel. Native SQL security checks remain
real functions in that regression; an additional case verifies the post-write
capability re-pin/clock check raises on expiry. SQL seams use strict recording
doubles; these checks are not PostgreSQL concurrency or rollback proof. Initial local execution used the existing developer venv and
therefore is only preliminary: pinned105 image and disposable PostgreSQL validation
must be reported independently. No production or full P0 acceptance is claimed.
