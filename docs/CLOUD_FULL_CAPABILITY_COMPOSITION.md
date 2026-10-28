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
