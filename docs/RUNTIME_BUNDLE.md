# Native Runtime Bundle v1 — CA-P2-01A

2026-10-21; owner Luke Ding; source base6dbb2a8d. Native producer-owned
contract and **offline validation only**. [Design](superpowers/specs/2026-10-21-runtime-bundle-contract-design.md),
[plan](superpowers/plans/2026-10-21-runtime-bundle-contract.md),
[machine schema](contracts/runtime-bundle-v1/envelope.schema.json),
[component catalog](contracts/runtime-bundle-v1/component-catalog.json),
[example](contracts/runtime-bundle-v1/example-envelope.json),
[canonical manifest bytes](contracts/runtime-bundle-v1/manifest.canonical.json),
[digest vectors](contracts/runtime-bundle-v1/digest-vectors.json),
[portable negative vectors](contracts/runtime-bundle-v1/negative-vectors.json).

## Scope and consumers

This implements strict frozen Bundle models, configuration validation, declared
asset closure, deterministic hashing and explicit reader compatibility checks.
It does not publish/store/admit a Bundle or change an effective Release/Task.
`GET /management/v1/target` still reports bundleManagement/nativeScriptAbi=unsupported.
There is no new HTTP endpoint, management credential/action or migration.
Go consumes these versioned artifacts through a later explicit adapter; it must
not import Python internals or reuse platform P0 schema names as native contracts.

Existing `agent-definition/1`, `agent-definition-snapshot/1`, Host admission,
Coverage v1/v2 and recovery stay unchanged. New Bundle bytes are an independent
format, not new optional fields in old models. A future Definition format will
reference a Bundle one way. A Bundle never contains the Definition/Release digest
that would depend on it, so there is no digest cycle.

## Runnable public entry

From this checkout after `make sync`:

```sh
uv run python scripts/validate_runtime_bundle.py --input docs/contracts/runtime-bundle-v1/example-envelope.json
uv run python scripts/validate_runtime_bundle.py --schema
uv run python scripts/validate_runtime_bundle.py --catalog
```

Success exit0 returns only contract_version=cloud-agent.bundle-validation/1,
bundle_digest,catalog_digest,validation_only=true,execution_supported=false.
Bad candidate/regular-file input returns exit2 and `{"error":{"code":"INVALID_BUNDLE"}}`;
no validation details, file contents or instructions are echoed. CLI argument errors
use standard argparse errors. It accepts a bounded local regular file; FIFO/device/
directory and oversized input fail without resolving anything. Outputs are stdout;
no candidate rewrite, output directory, database, remote request or secret lookup.

Python consumers use `agent_core.domain.runtime_bundle`:

- `parse_runtime_bundle(raw: bytes)` validates untrusted JSON into a frozen envelope.
- `canonical_runtime_bundle_bytes(manifest)` returns the manifest's exact hash bytes.
- `seal_runtime_bundle(manifest)` revalidates a candidate manifest and computes envelope digest.
- `runtime_bundle_json_schema()` and `runtime_bundle_catalog()` return fresh JSON values.
- `runtime_bundle_catalog_digest()` and `builtin_component_pin(domain)` expose exact native pins.
- `require_bundle_compatibility(envelope, supported_bundle_abis=..., supported_component_digests=...)`
  rejects readers missing an exact ABI/component descriptor. These capabilities must
  come from trusted reader code; this is not a worker self-report or admission hook.

Use parse at trust boundaries. Native JSON Schema describes shape; the Python
validator additionally checks catalog/asset closure/hash and compatibility rules.
The published example uses synthetic asset pins, not available packages/images.
Generic JSON Schema validation alone is insufficient. Neither success nor a digest
is signature verification, trusted publication, available assets or execution proof.

## Wire and digest

Envelope: required schema_version=cloud-agent.bundle-envelope/1,bundle_digest,
manifest. Manifest: required schema_version=cloud-agent.runtime-bundle/1,scope,
engine,baseline_config,catalog_digest,domains,lock,build_evidence. Unknown fields
and versions fail; no defaults are inferred or values silently trimmed/coerced.

Scope carries exact authority_issuer,namespace_id,product_id,environment,target_id,
deployment_id. The issuer is bounded HTTPS without userinfo/query/fragment; it is
an opaque authority binding here, never fetched. Engine kind=cloud-agent, image
pin,bundle_abi=cloud-agent.bundle/1,script_abi=unsupported. This ABI identifies the
new validation contract, not an already implemented execution assembly protocol.

Each asset pin has kind,id,version,digest. Kinds: image,baseline-config,component,
provider-profile,output-schema,build-evidence. IDs are bounded stable ASCII path
identifiers, not URLs, file paths or executable references. Version is exact
major.minor.patch with no range/tag/prerelease/leading-zero aliases; digest is
exact `sha256:` plus64lowercase hex. No case/prefix/whitespace normalization.
Image pin identifies a logical image artifact/version/digest; its trusted resolver and actual image bytes are not consulted.
A baseline-config artifact digest is mandatory; no process Settings are guessed.

The lock is ordered by (kind,id,version); identity (kind,id) is unique. It must
match the exact distinct references in all20components, engine image, baseline
config, model provider profile, instruction output schema and build evidence.
Missing/extra/conflicting pins fail. Distinct assets may have identical content
hashes; this does not collapse their identities or remove required references.
Build evidence references are declared, not validated evidence of a successful build.

`bundle_digest = 'sha256:' + SHA256(canonical(manifest))`.
Canonical profile: Python JSON sorted object keys, ensure_ascii=True, compact
separators `,` and `:`, no trailing newline, ASCII bytes (also UTF-8). Non-ASCII is
escaped, including surrogate pairs for supplementary characters; lone surrogates
are rejected. Exact instruction text, including whitespace/escapes, is preserved.
Numbers in Bundle values are bounded integers; model token/temperature/retry bounds
are below. Floating numbers (including1.0), NaN/Infinity, bool-as-int and silent
conversion fail. This is explicitly **not RFC8785/JCS**. Go implementations must
match published byte vectors, including Unicode/escapes and ordering; hashing a
Go default JSON encoding is not sufficient. Metadata JSON Schema/catalog legitimately
contains booleans; primitive Bundle fields still reject booleans where integers are required.

The11published negative cases apply simple path/value patches to a fresh example and
independently recompute the outer digest before validation. They must fail for their
semantic violation, not for an old hash; component substitution also updates its
lock pin. These fixture operations are not a management patch API. Additional raw
JSON and boundary negatives live in tests/agent_core/test_runtime_bundle_validation.py.

The digest covers scope, ABI, catalog, every parameter, lock and evidence pin,
and excludes only the outer envelope. Object key ordering/insignificant JSON
whitespace does not change it. Array order must meet the contract's explicit
ordering. Unknown future formats are never reinterpreted as v1.

## All20domains, validated configuration and fixed components

Every domain must appear. All component IDs/versions/descriptor digests must equal
the native allowlist. The catalog digest binds the sorted descriptors and their
parameter schemas, source references and pinned reasons. A component's digest is
its **descriptor hash**, not an assertion that a code/image/config artifact was
loaded. The image and baseline artifact pins are separate. This distinction must
be retained by platform adapters and future runtime assembly.

| Domains | v1 parameters | Meaning |
| --- | --- | --- |
| model | provider_profile pin,model,context_window_tokens,max_output_tokens,max_retries,temperature_milli,thinking | configurable candidate; validation only |
| instructions | system_text,business_text,locale,output_schema pin | configurable candidate; validation only |
| engine,execution,context,memory,content,native,addons,tools,lifecycle,policy,sandbox,storage,transport,frontend,triggers,budget,verification,operations | empty object | pinned; reason=requires-runtime-assembly |

Model context/output tokens are strict integers1..1048576, output<=window;
retries0..3,temperature_milli0..2000,thinking auto/enabled/disabled. These are
v1 validation limits; they do not override an actual provider's supported options,
capability negotiation, user authority or task budgets. Provider profile must be a
provider-profile pin, never a raw URL/key/env secret. Instruction strings are each
at most32768characters, locale bounded BCP47-like syntax, output_schema a typed
output-schema pin. Instruction text is data, never evaluated as Python/shell.
No automatic secret detection is promised for arbitrary instruction text; do not
put credentials there. Raw input/error data must not be written into logs.

The18pinned bindings cannot smuggle a parameter override, script, addon or permissive
policy through a dictionary. Their catalog source_refs point to existing native
contracts/implementation as provenance. They do not enumerate every Settings field,
freeze actual deployed configuration or prove dynamic replacement. This is complete
domain declaration and closed validation, not completion of20domain runtime configuration.
Changes to a component schema alter its descriptor/catalog digest; publication must
review/bump the relevant native version rather than silently editing published goldens.

## Resource and compatibility rules

Untrusted raw JSON is limited to256KiB, depth24,node budget8192; canonical bytes
also bounded. Duplicate keys (at any level), invalid UTF-8/BOM, malformed JSON,
excessive nesting, nonfinite/floating numbers and lone surrogates fail. Frozen
nested models/tuples and per-call state prevent caller mutation of an accepted
manifest. No network/DB/global lock or external operation occurs during validation.
Parallel deterministic tests are correctness checks, not QPS/latency or HA evidence.
The CLI is an operator's offline tool, not a concurrent HTTP service.

| Input / reader | Result |
| --- | --- |
| Current Bundle+matching catalog/closure/hash and validation reader | validation only; execution unsupported |
| Unknown envelope/manifest/ABI/component/parameter or changed catalog | reject; no fallback to defaults/latest |
| Reader missing Bundle ABI or any component descriptor | INCOMPATIBLE_BUNDLE; never substitute another version |
| Existing Definition/Snapshotv1 | old parser/hash/recovery unchanged; not accepted as Bundle |
| New Bundle passed to legacy Definition/Snapshot | reject; no field injection or migration |

All behavior remains additive and offline. No installed service is activated by
installing this package or running the validator. The catalog is a validation
allowlist, not a plugin loader; no registry fetch, secret resolution, output schema
fetch/evaluation, sandbox image pull or scripts run here.

## CA-P2-01B and evidence boundary

Next native work owns explicit storage/publication authorization/CAS/idempotency,
asset authenticity and exact semantic resolution, compatible Definitionv2/Task
snapshot binding, actual model/instruction assembly and incompatible Worker refusal.
New Tasks must freeze the new Bundle, old Tasks must retain old bytes/recovery.
Current authority and Coverage proof gates remain authoritative at sensitive actions;
Bundle configuration cannot grant rights or weaken publication proof requirements.
Online management needs an independently approved authenticated contract; existing
read-only rtmg credentials cannot be silently widened. No CA-P2-01B code is included.

[Validation evidence](evidence/ca-p2-01a/validation.json) records actual focused/full
gates, canonical/schema/CLI/legacy checks, source hashes and skipped boundaries.
Legacy fixtures are deterministic examples from unmodified v1 code at the base pin,
not production data or proof of a live database upgrade. Real business/Worker/model/
sandbox/HTTP/production acceptance belongs to later tasks.
