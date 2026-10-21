# CA-P2-01B — Bundle binding and execution design

## Contract and authority

Reuse the published Bundle v1 envelope without changing its schemas, catalog or golden bytes. Add independent agent-definition/2 and agent-definition-snapshot/2 models; keep the v1 model and digest algorithms unchanged. A v2 Version contains the validated Bundle plus its resolved immutable execution configuration. Its digest covers all v1 reference content and the complete resolved configuration. A Task snapshot embeds that Version and binds the existing Release/eval identity, self digest and scope. Parse versions/snapshots explicitly; unknown formats fail closed. Pydantic serialization must retain v2 fields through TASK_PREPARED, projections, memory scopes and recovery.

Materialization reuses fresh draft validation and existing publisher ceilings, additionally requiring exact runtime-bundle/<digest hex>@1 grant. Never save a v1 candidate then overwrite it with v2. The existing exact Version eval gate remains required for publication; Bundle environment must match publication/binding environment. Bundle content supplies configuration, never identity or expanded permissions. Current Host, tool, security, lease, cancel and Coverage authority checks remain mandatory.

## Trusted asset resolution

Use an optional operator-mounted private execution catalog, bounded strict JSON with no executable imports, URLs to fetch or request-selected paths. Catalog approves one complete Bundle scope, image, baseline, provider profiles, text output schema and build-evidence pins. Recompute public provider profile digests from canonical nonsecret content. Accept only supported text output; reject unknown output adapters instead of silently ignoring them. Build evidence and image pins are operator-approved identities, not proof of a running OCI image; deployment attestation is outside this local slice.

Provider profiles specify verified HTTPS endpoint, provider name, a secret environment variable name and approved exact models. Actual credentials never enter Version/Task/event payloads. Resolve approved pins before storage transactions. Freeze resolved profile content in the Version, so recovery does not look up the latest profile. Missing catalog disables v2 materialization/execution while legacy behavior remains available.

## Runtime baseline and compatibility

The Bundle exposes model/instructions configuration; the other eighteen domains remain pinned. An operator-owned random key computes HMAC-SHA256 over canonical complete Worker settings excluding model (fully replaced for bound tasks) and the catalog file path. The baseline ArtifactPin digest is this opaque fingerprint: it detects drift including existing extension, sandbox, storage and transport settings without publishing secret values or unsalted secret hashes. The key stays in the private catalog. A changed key or any pinned setting causes refusal, not fallback. This deliberately makes some rotations require a compatible retained worker/baseline. Do not claim historical v1 tasks have retroactive settings snapshots.

First preserve committed-completion recovery and pending durable Turn-close reconciliation (ADR-026). After preflight close healing and before any new external execution, Worker recovery validates the embedded Version/Bundle/assembly/snapshot digests and exact configured scope, image, supported ABI/catalog and baseline before model, tools, sandbox or Coverage dispatch. No registry/current release lookup, remote resolution or shared mutable service settings. Incompatible Worker setup uses the existing retryable refusal path so a matching worker can recover the same durable Task. Concurrent tasks use task-local immutable model settings and instruction composition. Old v1 tasks continue their existing baseline path; v2 tasks either use their frozen configuration or refuse.

The actual model adapter receives exact model, output/context limits, retry count, temperature and supported thinking mode. Unsupported provider/wire/thinking combinations fail before execution. Instructions append to existing governed context and do not replace policy. Every request path (complete, streaming, prepared) must honor bound limits. Coverage must never silently use process-default model/instructions; preserve source-owned qualification/proof guards. If its current proof contract cannot represent a bound option, refuse that v2 combination before any effect and document the supported boundary rather than weakening proof.

## Storage and rollout

Add offline additive v110 sidecar for full v2 Version JSON with scoped foreign key. Base Version row and sidecar commit atomically. Old rows/fields remain unchanged; v1 reads do not require the sidecar table. Missing/corrupt sidecar, conflicting version IDs/numbers and mismatched relational scope/digest fail closed. Recovery uses durable Task content only. No in-place data rewrite, startup migration or production action.

## Verification

Run meaningful red/green tests for digest tampering (recomputed nested digest negatives), exact grants and cross-scope/environment rejection, v1 golden compatibility, serialization/recovery after Release/profile changes, incompatible Worker before effects, actual provider body and instructions, independent concurrent tasks, and Coverage regressions. Require disposable PG v2 round trips/atomic conflicts and v109-to-v110 preservation; a skipped PG baseline is not acceptance. Freeze source before final make test/check, report skips separately, commit/push task branch only.

## First executable compatibility matrix

- Bound v2: approved OpenAI-compatible Chat provider, thinking=auto, plain text output, fixed exact model/context/output/retry/temperature and instructions.
- Bound v2 refuses nonempty local Skill roots (all four scopes) and local mcp_servers; a path-only baseline cannot freeze their contents. Existing cloud extensions retain their accepted-command immutable snapshots and digest verification. V1 capabilities stay unchanged.
- Bound v2 unsupported: DeepSeek role-routed/Responses providers, non-auto thinking, structured output and strict Coverage. Reject before model/tool/sandbox/Coverage dispatch, never substitute process defaults.
- Existing v1: all current providers, local/cloud execution and Coverage mechanisms remain on their existing paths unchanged. Historical v1 settings were not recorded and cannot be reconstructed retroactively.
- Explicit parse input sites: Task recovery, TaskPrepared contract, workspace domain/projection, memory scopes, SQLite workspaces and PostgreSQL workspaces, PostgreSQL Version sidecar. Explicit subclass-preserving serialization is also required on base-typed Pydantic fields.
