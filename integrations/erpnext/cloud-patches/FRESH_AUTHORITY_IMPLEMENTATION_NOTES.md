# Fresh ERP authority — source-only review candidate

This candidate is disabled by default (`ZEBRA_ERPNEXT_FRESH_AUTHORITY=disabled`).
It does not change the legacy containment policy, activate the private workspace
consumer, migrate a database, configure a service, or enable the Agent's full feature set.
The existing `private_workspace_not_activated` refusal is unchanged. No real model,
ERP business operation, production write, or service activation was used in these checks.

## Source provenance and isolation

Worker base: `sha256:33b93abc4b257d0639730f2e2c388d765f092d7979a03b117f6387b0049c0e18`.
API base remains `sha256:2156443eea6ad9330853d16ece204dfa0995a41e5b5b677063386216797daaef`.
New Worker baseline modules come from the existing hash-captured 105 audit source.
The two model adapters and native effect guard were extracted read-only from that
exact Worker container/image and byte-hash verified. No dirty 107 Cloud source is used.
Existing attachment106 and legacy overlays are retained in the Worker Dockerfile.
Historical initial/followup/legacy manifests are not rewritten; `fresh-slice-sha256.json`
freezes the cumulative source for this review.

Host changes live only under `host-overrides/zebra_erpnext/`; the live app source
`zebra_erpnext/gateway.py` is unchanged. `host-baseline` captures clean HEAD gateway/cloud
for review and the callback mock check. `Dockerfile.fresh-host` requires a local image tag already inspected to equal the
approved ERP image config ID and copies only the two Host overrides. A bare
`sha256:<config-ID>` is not a Docker FROM reference: Docker may parse it as
`docker.io/library/sha256:<ID>` and attempt a remote pull. Never pass a config ID
directly and never fall back to a remote or floating base. Before building:

```
ERP_REVIEW_BASE=erpnext:zebra-maintenance-guard-review
ERP_APPROVED_ID='sha256:<approved-full-image-config-ID>'
test "$(docker image inspect --format '{{.Id}}' "$ERP_REVIEW_BASE")" = "$ERP_APPROVED_ID" || exit 1
docker build --pull=false --network=none --file Dockerfile.fresh-host \
  --build-arg ERP_HOST_BASE="$ERP_REVIEW_BASE" --tag erpnext:fresh-authority-host-review .
```

The tag equality check must succeed before the build; the Dockerfile alone does not
prove this identity.
This avoids accidentally including these unreviewed Host changes in the parallel UI release.

## Boundary behavior

- Startup opt-in requires ERP namespace, stored binding loader, pinned profile, expected
  workload identity, configured HMAC secret and validated HTTPS endpoint. Default is disabled.
- With fresh opt-in, containment and the fresh probe precede even completion recovery,
  whose bounded reader includes full private answer/input payloads. Disabled mode retains
  the previous completion-first order. Before progress/input/attachment recovery, load and revalidate the typed stored TaskBinding,
  match the indexed Task, frozen Host context digest, Task/thread/principal/Run/scopes/expiry,
  capability ceilings and pinned profile identity. A fresh control probe must succeed first.
- The probe reuses `resolve_pinned_gateway`, native `HostToolGateway.invoke`, native HMAC
  body/headers and `HttpHostToolTransport.request`. It supplies a private singleton
  `erpnext.authority` HOST/READ manifest using only existing `erpnext.read`. It does not
  discover/publish a tool or add any model tool or Task capability. Its arguments/output
  are fixed and bounded; callback permits no additional argument keys.
- Native HTTPS/no redirects/no credentials/query/fragment/IP-literal and response/deadline
  checks remain. A composed client preserves its own CA/transport; created clients use
  the existing native SSL trust-store helper. No verify=false is introduced.
- Host callback runs through `delegated` and `set_user(record.user)`, then actual
  `cloud.owned` / fresh User.enabled / Company.read. It checks mapped owner/company/workspace,
  Task/thread/Run, active Run, dispatching/running status and admission pause. No grant is
  minted and no Cloud request or business write occurs. Local naive Frappe expiry is
  interpreted in the site's timezone, compared with the frozen UTC expiry in that timezone,
  and returned in UTC after min-clamping. No expiry is extended.
- `select_attempt_authority` retains the actual BoundHostExecutionAuthorityResolver type
  with an optional fresh checker. Existing verified binding renewal remains native;
  same-attempt revalidation clamps to prior and Host expiry. Extension snapshots and
  Context memory selection receive fresh probes before access. Once AttemptAuthorityEvidence
  persists, the memory/context boundary uses the same recorder-backed fresh check, then
  refreshes native claim/input revisions before the materialization request.
- Once native attempt evidence exists, each runtime/context/tool/model/publication check
  uses the existing recorder's mutation/RLock for prior snapshot -> probe -> typed native
  EXECUTION_AUTHORITY_REVALIDATED append. Denied/expired/revoked decisions retain prior
  snapshot references. Appends do not call fresh through ownership_check, so no recursion.
  Business/provider/tool I/O occurs outside that mutation lock. Existing IDs are retained:
  toolCallId, provider adapter's existing call_id, output_id, receipt digest/artifact ref.
- Every shared WorkerToolGateway._execute route checks fresh, including reads, files,
  command, MCP, skills, management, client and Host calls. Host receipt reconciliation
  also checks fresh. The native FencedEffect outer execute/exact/payload/dispatch seams
  check before schedule/read/dispatch; actual inner execution checks again. Known rejection
  before dispatch uses native failed_no_effect. A denial at the inner WorkerToolGateway
  entry is returned with native returned/rejected/not_executed evidence, preserving the
  original toolCallId so the outer fence also settles it as failed_no_effect. Only that
  entry check catches ExecutionAuthorityResolutionError; errors inside a started handler
  remain exceptions. Once dispatch starts, native uncertainty,
  lease/fence/idempotency/receipt behavior is retained; business work is not blindly retried.
- OpenAI-compatible and DeepSeek Responses complete/complete_stream check before every
  HTTP attempt outside their retry catches. This includes normal, repair, continuation
  and PublicExpression calls that use these composed adapters. Streaming kwargs/protocol
  are unchanged; there is no per-SSE-chunk probe. Provider-internal retry retains its
  existing call_id. A provider lacking this native seam is refused when fresh is composed.
- WorkerProgressRecovery.persist_with wraps its underlying PUBLIC_OUTPUT sink; both normal
  canonical publication and repair_commentary pass through it. Transient output admission
  checks once at start_public_call, with the original Harness call ID, before opening a lane.

## Explicit unavailable / review limits

- The earliest pre-input probe and pre-snapshot extension probe produce a typed in-process
  decision; durable native authority evidence begins at persist_attempt_authority. They do
  not invent a prior snapshot when none has been recovered. Review this evidence boundary
  explicitly: it is not a claim of durable journaling before input preparation.
- Maintenance Memory/title execution is unavailable with fresh opt-in until a separately
  reviewed terminal-safe fresh evidence contract exists. Worker-loop startup and candidate
  selection skip it before the oldest/LIMIT query; direct recover returns false before claim.
  No fake memory-completed receipt or retry record is written. Normal Cloud finalization
  already defers Memory/title side effects to this path. This is a deliberate fail-closed
  limitation, not completed full Agent functionality.
- Coverage-specific execution is explicitly refused under fresh opt-in. Native prepared
  model dispatch is also refused when a fresh checker is installed. Coverage has separate
  reservation/settlement/execution boundaries and is outside this bounded slice.
- A revocation after a successful check can race an already-started external effect or
  stream; the existing uncertain-effect evidence is preserved. No distributed atomicity
  between ERP permissions and external side effects is claimed. Transient frames in an
  already admitted provider request are not individually probed.
- No physical quota/mount isolation, private-workspace activation, real ERP HTTP/DB role
  revocation, PostgreSQL concurrent journal acceptance, or real-model acceptance is proven
  by these doubles. Root performs isolated actual105/ERP acceptance after independent reviews.

## Runnable checks and observed results

`tests/check_fresh_authority.py` is one assertion-only test file, no new framework/dependency.
It runs with `tests/overlay_imports.py` over the exact 105 Worker image. All original and SPEC revision groups passed:

1. Native fixed Host HMAC, malformed/timeout/expiry-expansion/Host-ID drift rejection,
   allow -> revoke with valid lease/JWT and zero file/command/MCP/client/management dispatch,
   24 parallel prior-linked journal entries, selected Bound identity, model retry refusal,
   streaming refusal, opt-in/startup validation and wiring assertions.
2. Early denial prevents progress/input recovery; durable and repair publication deny
   before canonical sink; maintenance never queries candidates.
3. Real Host gateway.invoke/delegated/cloud.owned/authority.check functions with strict
   Frappe boundary doubles: disabled User, removed Company read, owner/company/workspace/
   task/thread/run drift, deleted/cancelled/pause, invalid HMAC, user restoration and
   Asia/Shanghai 5-minute Grant clamping a 10-minute UTC context.
4. Native FencedEffect outer admission and pre-dispatch failed_no_effect; unchanged
   post-dispatch uncertain handling with one downstream call and no business retry.
5. SPEC regressions call the real shared execution entry for READY/RUNNING and both
   committed/no-completion payload stores: revoked Host leaves the completion reader at
   zero calls. Disabled mode preserves completion-first behavior. Outer fresh allow then
   inner fresh denial produces zero downstream calls, exactly one native fail_no_effect,
   no uncertain settlement, unchanged call/effect identity, and sticky denial of the next
   model check. The real prepare_worker_context, AttemptAuthorityEvidence.persist, selected
   Bound resolver, _refresh_claim and _refresh_inputs paths persist initial evidence and
   then deny or allow Context selection. Denial references the just-persisted snapshot
   and permits zero materialization reads; allowed evidence advances both claim/input
   revisions before exactly one materialization call.
6. An ExecutionAuthorityResolutionError from an already-started tool handler is not
   converted by the Worker entry catch; the native outer fence retains uncertain evidence.
7. Both shared native TaskBinding readers select binding_digest and snapshot_json from
   the same latest row and compare the recomputed typed snapshot digest with the stored
   64-character lowercase hex digest. Missing/malformed/different digests fail closed.
   Tests cover both public load wrappers, readonly transaction setup, native lineage
   rejection and the actual loop.py loader closure through the real fresh execution
   entry: a mismatched stored digest permits zero Host probes and zero private recovery.
   The shared fix also covers HTTP input, rollover/handoff, proof batches, context and
   direct-control callers; no fresh-only replacement loader is introduced.

Exact invocation (disposable container, no network, read-only root; only source mounted):

```
docker run --rm --network none --read-only --tmpfs /tmp \
  -v /tmp/zebra-fresh-source-check-20261023:/review:ro \
  --entrypoint /app/.venv/bin/python \
  sha256:33b93abc4b257d0639730f2e2c388d765f092d7979a03b117f6387b0049c0e18 \
  /review/tests/check_fresh_authority.py
```

The existing `check_legacy_containment.py` also passed on the same exact Worker and
cumulative overlays. Existing `test_followup_http_input.py` (including initial HTTP input),
`test_clarification_attachment_dispatch.py` and `test_local_clarification_rejection.py`
also passed on the exact Worker with network disabled. These are source-level checks;
no new PostgreSQL integration run was performed by the implementation agent.
`test_build_initial_images.py` and `git diff --check -- cloud-patches`
passed. No review image was built or service activated by the implementation agent.


## QUALITY continuation revision and release boundary

The shared execution continuation entry now reuses native `_refresh_claim` after the
fresh extension/context journal checks and before `recover_and_start_continuations`.
This adopts the recorder's committed Session/Workspace and matching Worker authority;
primary drift retains native bounded recovery and later append CAS protection. Disabled
fresh behavior is unchanged. No continuation-specific constructor, identity, retry or
exception policy is modified.

The assertion-only check executes the actual shared startup block, actual continuation
startup/lifecycle helpers and native DurableHarnessEventRecorder with a CAS-checking
transaction double. All five branches (approved, completed, clarification, child,
client-effect) start at the refreshed revision with original tool/continuation IDs.
An independent primary advance after refresh still rejects the first append; no
continuation event is committed. Full fresh checks, legacy containment and follow-up
HTTP input checks passed on exact105 Worker, UID 65532, network none and read-only root.
This is source/isolated evidence, not production activation or PostgreSQL integration.

Release verification remains OPEN for an early fresh refusal before prior authority
exists. Native classic command_consumer catches ValueError as skipped without saving
reject_command's idempotent rejection receipt, so its scan can revisit the command.
Migrated command_wakeup_consumer consumes the future exception and releases the slot;
execution's heartbeat releases the lease. Native command_wakeup_recovery then treats
an accepted receipt without its lease as uncertain/requires_reconciliation, rather
than an explicit permission refusal. The composed Cloud ready scan is disabled
(`scan_ready_sessions=not migrated and settings.deployment != "cloud"`); no Cloud
ready-scan crash has been observed or claimed.

Smallest proposed follow-up before activation: identify a typed, bounded early fresh
refusal at the exact pre-private-read point, keeping original command/lease identity.
Classic command handling can reuse reject_command's existing receipt/exclusion after
extending its typed reason set. Migrated handling needs an explicitly reviewed,
fenced metadata-only disposition for an already-accepted command, preserving started
or uncertain work and preventing automatic rewrap. Reuse existing command receipt
and pending-outcome machinery after verifying its supported state transitions;
do not blindly apply a pre-handoff refusal to an accepted receipt. Validate no private
progress reads, no invented prior snapshot, no setup/terminal failure event, bounded
one-command disposition, unchanged control handling and no automatic replay. This is
a proposed bounded follow-up, not implemented or verified by this revision. Converting
the error into WorkerExecutionError is unsuitable: its native catch recovers private
progress and finalizes a setup failure. Fresh defaults, maintenance/coverage refusals
and legacy private-workspace containment remain unchanged.


## Isolated early-refusal follow-up

The early-refusal OPEN item above is historical to the approved df8 revision. The isolated bounded follow-up is now implemented; see `EARLY_FRESH_REFUSAL_REVIEW.md` for its exact source, test and remaining activation boundaries. This does not retroactively claim the earlier revision handled early refusal, nor does source/QA completion authorize activation.
