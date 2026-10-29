# Full Cloud capability composition

Task CLOUD-FULL-CAPABILITY-COMPOSITION-20261028 supports authorized business
adapters without importing their domain rules into the Runtime.

## Implemented foundation (not live acceptance)

- Disabled-by-default `ZEBRA_HOST_EXECUTION_AUTHORITY_ENABLED=true` composes a
  private, pinned Host control call. The server chooses TOOL (`host.authority`
  default) and SCOPE (`agent.run` default). It is never a model-visible tool.
- Check existing Task binding/profile/current Host identity/expiry before private
  inputs and materialization, gateway setup, every physical Chat/Responses model
  attempt, prepared calls, tools and receipt reconciliation. No positive cache;
  refusal escapes provider retries. Ownership/cancellation checks surround probes.
- Host response requires `decision=allowed`, exact bound Task/thread/Run/principal/
  workspace identity, optional uniquely bound resource dimensions, canonical
  SHA256 metadata digest and an expiry no later than the bound grant. Each
  in-attempt check narrows and journals existing ExecutionAuthority evidence.
  A refusal latches for that attempt. Unsupported coverage composition refuses.
- Workspace resolver accepts trusted prepare/verify callbacks from deployment
  composition. Resolve-ready verifies, never allocates; default local behavior
  and native runtime quota validation remain unchanged. Hooks alone do not prove
  a filesystem is quota-isolated; the deployment must supply and test both.
- `GET /tasks/{id}/artifact-segments?after=-1&limit=50` reads bounded index pages
  (max100+lookahead). Existing Artifact list/detail/content accept `segment_id`;
  primary indexed Task membership is mandatory before any selected segment read.
  Current segment remains the default. No arbitrary Session proxy or GET repair.
- Host user-memory management scopes inventory and individual mutations to exact
  user/tenant/workspace. Bulk/profile/tenant-wide legacy paths fail closed for
  Host callers; local/operator APIs remain compatible. Manual creation records
  the same source Task/current Host scope and uses native administrative CAS.
  Lists serialize typed records without replaying source conversations.

## Validation

`make check` passes (runtime product boundary, file sizes, Ruff,1435 typed modules,
release evals and progress risk/repair gates). Focused worker execution regression
90 passed;75 additional focused checks passed. Model transport retry/stream, authority identity/revocation, volume
boundaries, Task Artifact history and scoped Memory have no-model regression.
No model/search requests, production changes, original Task replay or Search/MCP
restart occurred. Live full-runtime, S3/quota, schedule exchange and ERP/browser
compatibility remain separate gates in the ERP integration task.

## Deployment boundary

Use a new immutable release/namespace for new conversations; retain original105
services and Runs for read/recovery. Do not enable a feature merely because an
endpoint exists or an environment flag is present. Freeze source and images,
validate native HTTP/storage and fresh Host revocation against isolated data,
then activate only the verified capability matrix. Memory selection under a
Definition must retain its original Definition scope; do not broaden queries.

## Schedule and startup boundary follow-up

- Keyed schedule creation derives one owner-scoped identity and checks frozen intent, including after lost HTTP acknowledgement; existing unkeyed clients stay compatible. Scheduled AG-UI admission preserves explicit extension selection and v2 capabilities.
- Fresh Host startup refusal/unavailability suspends the original session with a finite reason and no model retry. Cancellation is checked before private input. Researcher child probes use only verified durable parent lineage; child permissions remain narrowed.
- Ordinary opaque workspace references now use the same trusted resolver as Bundle tasks. Plain local paths pass through. Construct the provider before allocating a workspace, so missing credentials cannot allocate storage.
- Focused workspace/bundle gate21 passed; previous combined gate110 passed; make check passes1436 typed modules. Full deployment/ERP acceptance remains in the paired integration task.

## 2026-10-29 Cloud input and connector admission repair

Actual isolated ERP→Native→S3 requests exposed two latent generic defects: local
store_payload was called on Cloud metadata, and a frozen Host manifest still
produced an unbound connector placeholder. Cloud input publication now writes
immutable object receipts outside SQL and commits exact input events/metadata
with the Task admission or message stream CAS. No Worker lease is fabricated: API
input metadata records the real control-plane epoch and admitted event revision
under an explicit api-input owner. Failed/unknown writes are never blindly
deleted. Local payload behavior stays unchanged; no schema change. Source
workspace idempotency uses the scoped key and returned instance, with unowned
source ownership bound to the root in the admission transaction.

Admission now pins the actual registry profile only when its exact frozen
manifest still matches; registry drift refuses before private object I/O. Old
bindings are not rewritten. Fresh Host checks remain strict.

Real isolated PostgreSQL17.5/S3 gate passed: two-input admission rollback, exact
object reads, foreign Session denial, atomic follow-up input, stale CAS refusal
without duplicate, and explicit epoch/revision provenance. Three unit checks,
14 input/pin/renewal checks and51 focused extension/authority checks passed;
make check passes1438 modules. Full suite and paired ERP/volume/browser gates
are tracked separately and are not inferred from this result. No model/search
requests, original Run replay, production cutover or Search/MCP restart.
