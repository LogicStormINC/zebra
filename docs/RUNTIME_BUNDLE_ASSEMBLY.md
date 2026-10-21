# Runtime Bundle binding and Worker assembly (CA-P2-01B)

## Delivered boundary

CA-P2-01A defines immutable Bundle v1 bytes, pins and validation. This slice binds that exact contract to new Definition v2 and Task snapshot v2 formats and executes a bounded, explicit subset. Published Bundle v1 schemas/catalog/vectors and historical Definition/Snapshot v1 digest algorithms are unchanged.

| Path | Behavior |
| --- | --- |
| Existing v1 Definition/Task | Existing providers, runtime, capabilities and Coverage path remain available; no automatic Bundle upgrade. |
| Bundle v2 model | Approved OpenAI-compatible Chat endpoint, exact model, context/output limits, retry count and temperature; thinking must be `auto`. |
| Bundle v2 instructions | Frozen system/business instructions and locale appended to governed context; canonical plain-text output adapter. |
| Other 18 Bundle domains | Pinned to approved Worker baseline and existing runtime composition; not independently configurable in this slice. |
| Unsupported v2 combinations | DeepSeek role routing/Responses, non-auto thinking, structured output, unversioned local Skill roots/MCP servers and strict Coverage refuse before new external execution. |
| Native scripts / online Bundle management | Remain subsequent work; no new script ABI, package installer, management credential privilege or control-plane deployment action. |

The strict Coverage prepared-request and source-owned proof qualification does not admit the new Chat adapter. Existing v1 Coverage execution, historical coverage manifests and certificates remain unchanged. Refusing new v2 Coverage preserves that proof boundary; it does not claim Bundle-bound Coverage acceptance.

## Immutable binding

A `BundleDefinitionVersion` (`agent-definition/2`) contains the Bundle envelope and its approved resolved public provider profile (`RuntimeAssembly`). Its digest covers the complete configuration and existing policy references. The six policy references still require the publisher ceiling and fresh draft validation.

The Task's `agent-definition-snapshot/2` embeds that whole Version plus the existing production Release/eval identity and a self digest. It checks copied fields against its embedded Version. Scope includes issuer, namespace, product, environment, target and deployment. Publication and binding require the frozen environment to match the requested environment. Release evaluation still exact-pins Version identity and digest.

TASK_PREPARED, workspace projections, SQLite/PostgreSQL workspace storage, governed memory scope and Worker recovery preserve the v2 payload. Recovery uses that payload; it never resolves a new Release, mutable draft or current provider profile. Unknown schemas and tampered nested digests fail closed. v1 serialization/digest bytes remain available unchanged.

Historical v1 Tasks did not record complete effective Worker settings. This slice cannot reconstruct their old process settings retroactively: retain their original deployment baseline for historical recovery. The new no-drift guarantee applies to v2 configuration, with current authority still allowed to narrow execution.

## Publisher API and approvals

The existing authenticated Host publisher route `POST /agent-definitions/{definition_id}/versions` accepts an optional `runtime_bundle` envelope alongside `version_id` and `version`. Omitting it retains the v1 route. Supplying it requires explicit operator catalog composition and an additional exact publisher reference:

```text
runtime-bundle/<bundle_digest without sha256 prefix>@1
```

The API resolves approved local artifact pins before registry transactions and materializes v2 once. It does not first save a v1 Version and overwrite it. The response includes `schema_version`, `definition_digest` and the resolved nonsecret `runtime_assembly` for v2. Missing approvals/configuration cannot silently fall back to v1.

This reuses native Host publisher authentication/grants; `rtmg_` Runtime management credentials gain no Definition mutation authority. The existing API factory's empty publisher resolver remains fail-closed until the operator composes publisher grants. This slice does not add a new grant-management endpoint.

## Private execution catalog

Set `ZEBRA_RUNTIME_BUNDLE_CONFIG` to a mounted private JSON file in API and Worker roles. The file is optional for legacy v1. Keep it readable only by the service identity (for example mode0600 or a read-only Secret mount). No request may select its path; no remote asset fetch, executable import or credential body is supported.

The catalog schema is `cloud-agent.execution-catalog/1` and contains:

- `scope`: exact Bundle issuer/namespace/product/environment/target/deployment.
- `image`: approved Worker image ArtifactPin.
- `baseline_config`: approved baseline ArtifactPin.
- `baseline_key`: private 64 lowercase hex characters generated with `secrets.token_hex(32)`.
- `providers`: one to32 approved public provider profiles.
- `output_schema`: output-schema ArtifactPin with the native text schema digest.
- `build_evidence`: one to32 explicitly approved evidence ArtifactPins.

Each public provider profile contains `pin`, `provider: "openai-compatible"`, `base_url`, `api_key_env`, `models`, `max_context_window_tokens` and `max_output_tokens`. The URL requires HTTPS without userinfo/query/fragment. `api_key_env` is an environment variable name; its credential value exists only in the Worker environment. The pin digest is `canonical_provider_profile_digest(profile)`, excluding `pin` itself. Model and limits must fit the approved profile. Context reserves must leave input room.

The supported text output schema content is exactly:

```json
{"format":"text","schema_version":"cloud-agent.text-output/1"}
```

Its digest is exported as `TEXT_OUTPUT_SCHEMA_DIGEST`. Other schema digests are rejected. Image/build evidence pins are explicit operator approvals, not automatically fetched or independently authenticated artifacts. The mounted image identity is an operator assertion; actual OCI attestation/production deployment verification remains outside this local acceptance.

Catalog parsing is bounded at256KiB, rejects duplicate keys, floats and unknown fields, and returns fixed errors without private file contents. The baseline key is excluded from catalog repr/serialization and never enters a Version, Task, event or public response.

## Baseline preparation and execution

Compute the baseline ArtifactPin digest on the exact intended Worker configuration:

```python
from pathlib import Path
from zebra_agent_config import load_settings
from zebra_agent_config.bundle_settings import baseline_digest

# Run with the Worker's intended environment and config/default files.
key = Path("/private/runtime-baseline-key").read_text().strip()
print(baseline_digest(load_settings(), key))
```

Run that snippet with `uv run python` inside the repository. Generate/store the key privately, insert its value into the mounted catalog and place the resulting opaque digest in both catalog and Bundle `baseline_config`. Re-seal a changed manifest with `seal_runtime_bundle`; update exact lock pins and publisher grant together. The existing offline `scripts/validate_runtime_bundle.py` validates the envelope; it does not certify asset approvals or execute a Task.

The baseline uses HMAC-SHA256 over the complete settings dataclass except `model` and the catalog file path. Secret-bearing settings are not exposed as plaintext or unsalted public hashes. Model settings are entirely replaced by the frozen provider/model configuration. A different key, sandbox/storage/transport/extension setting or other pinned setting refuses execution rather than changing the Task's configuration. Non-local sandbox images must be content-addressed `...@sha256:<hex>`.

A settings path is not a content pin. V2 refuses all four local Skill-root settings and local `mcp_servers`, even with a matching HMAC; local file/stdio/server contents cannot otherwise be proven immutable. Existing cloud extension execution continues to require its exact accepted-command snapshot, verified package/object digests and current authority. V1 local Skills/MCP remain unchanged.

Changing the current catalog's provider list does not rewrite an existing Task. Retain compatible image/baseline/key workers for old tasks; changing a pinned setting or key requires an explicitly compatible retained worker. Provider credentials may rotate under the same frozen environment reference; credential values are never configuration snapshots. This is not a revocation API: fresh Host, policy, lease/cancellation and execution-authority checks still narrow every permitted action.

Worker ordering:

1. Recover committed outcomes and heal pending durable Turn-close records.
2. Validate embedded snapshot/Version/Bundle, current execution compatibility and provider credential availability before capability rejection can close a new attempt.
3. Refuse mismatched/unsupported workers with a retryable setup error, retaining the durable task for a compatible worker.
4. Resolve/materialize the bound Workspace only after compatibility; construct a task-local model gateway and configured context compiler; never mutate shared service settings.
5. Continue the existing authority, runtime/tool, harness and finalization paths.

No new model/tool/sandbox/Workspace materialization/Coverage dispatch occurs after a failed compatibility check. Background completion/title recovery also uses a compatible frozen gateway; absent/incompatible composition safely skips its optional title call without changing the committed outcome. A completed historical outcome is healed before this check, so refusal cannot invert an already committed success. Worker placement/backoff should select workers compatible with the pinned baseline; automatic rollout/routing infrastructure is subsequent work.

## Storage and rollout

Offline additive migration110 creates `agent_definition_bundle_versions` with a scoped foreign key to the existing Version row. Base v2 row and complete sidecar JSON commit in one transaction. Reads validate every base relational field against the sidecar. Missing, corrupt or mismatched payloads refuse; v1 reads do not require the new table.

Same-identity/content retries return the original durable Version, retaining creation metadata. Different content/version identity under a reused Version ID and reused version numbers conflict. A scoped PostgreSQL transaction advisory lock serializes Version creation; no remote I/O occurs while holding it.

No startup or production migration is executed by this feature. Before future production activation: apply additive migration through the established offline process, provision compatible workers and private approvals, and retain legacy baselines. This task changes source and local disposable test databases only.

## Evidence

See [CA-P2-01B evidence](evidence/ca-p2-01b/README.md) for final source fingerprint, focused tests, real disposable PostgreSQL acceptance, legacy/Coverage regression and full gate results. Local mock provider HTTP requests prove assembly consumption, not production provider or OCI/gVisor acceptance.
