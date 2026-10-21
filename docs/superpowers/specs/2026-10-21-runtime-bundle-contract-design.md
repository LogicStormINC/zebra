# CA-P2-01A Runtime Bundle contract design

2026-10-21; owner Luke Ding; native producer baseline6dbb2a8d. Scope authorized by current user and standing autonomous technical decisions. Implementation requires independent review; no deployment/migration.

## Decision and alternatives

Adopt an independent versioned immutable contract, generated schema/catalog, pure native validator and offline CLI. Reuse Pydantic2 and stdlib; no existing Definition/Snapshot mutation. This delivers real executable validation without claiming Worker assembly.
Alternative1: attach arbitrary dictionaries to existing Definitionv1; rejected because historical hashes/recovery and unvalidated defaults would change. Alternative2: implement online publication, storage and Worker assembly at once; deferred to CA-P2-01B because it adds distinct authority, persistence and rollout invariants.
Current user explicitly asked this scoped producer prerequisite; routine design choices proceed under prior delegated decision authority.

## Contract and ownership

Core owns deterministic frozen models/validation, never infrastructure/settings imports. Script is local file/JSON I/O only. Native docs/contracts/runtime-bundle-v1 owns generated schema/catalog and positive/canonical/digest vectors; platform P0 Overdoze envelopes are historical design inputs, not accepted native formats.
Public surface is the Python parse/seal/canonical/compatibility API and scripts/validate_runtime_bundle.py CLI (--input, --schema, --catalog); no HTTP API or new management action this slice. Target descriptor bundleManagement/nativeScriptAbi remains unsupported. Go later consumes published native artifacts/explicit adapter, never imports Python internals.

Envelope schema_version=cloud-agent.bundle-envelope/1, bundle_digest=sha256:lowercase64, manifest schema_version=cloud-agent.runtime-bundle/1. Manifest includes exact scope (authority_issuer,namespace_id,product_id,environment,target_id,deployment_id), engine (cloud-agent,image pin,bundle_abi=cloud-agent.bundle/1,script_abi=unsupported), baseline_config pin, catalog_digest,20-domain bindings, exact lock closure and build-evidence pins. All fields required; extra forbidden and no silent trim/coercion of primitive values. No Definition/Release digest within Bundle: future Definitionv2 references Bundle one way.
Each asset pin is kind,id,version,digest; kind enum image/baseline-config/component/provider-profile/output-schema/build-evidence; IDs stable ASCII path identifiers, exact semantic version (no moving tag), lowercase sha256. URI/userinfo/query/path traversal and credential values are not asset locators. Image id uses stable repository path+version+digest, not floating tag. Declared assets are not fetched or executed.

## Twenty domains and allowlist

engine,execution,model,instructions,context,memory,content,native,addons,tools,lifecycle,policy,sandbox,storage,transport,frontend,triggers,budget,verification,operations must all exist. Each component binding pins native id/version/descriptor digest, compared exactly to built-in catalog. No user-supplied catalog or permissive fallback. Catalog digest binds sorted descriptors including parameter schema and source references. Source references are provenance, not proof a deployed image/config matches.
model and instructions expose strict configurable candidate parameters, validation-only. Model: provider_profile pin, explicit model identifier, context_window_tokens,max_output_tokens,max_retries,temperature_milli,thinking mode; output<=window, strict integer bounds. No endpoint/API key in parameters. Instructions: bounded system_text,business_text,locale and output_schema pin; text data is never evaluated. Other18 domains use pinned mode, exact fixed reason requires-runtime-assembly and empty parameters; arbitrary pinned params are rejected.
Each pinned domain maps to actual native source paths in the catalog/documentation. baseline_config and image digest are required declared closure pins; their actual bytes/config and consumption are unverified until assembly. This does not inventory every Settings field or pretend20domains already dynamically configurable. No script runner/addon resolution/security bypass.

## Deterministic bytes, limits and compatibility

SHA256 covers canonical manifest bytes only (envelope digest excluded), including scope,ABI,catalog,all config/pins/evidence. Encoding: JSON sorted object keys, ensure_ascii=True, separators(',',':'), no insignificant whitespace, UTF8 ASCII bytes. All contract numbers are bounded integers; floats,bool-as-int,NaN/Infinity,duplicate JSON keys,BOM/invalidUTF8,lone surrogates and unsupported types rejected. Instructions preserve exact text; object ordering/whitespace irrelevant, array order explicit.
Lock is sorted by(kind,id,version); duplicate identities or conflicting versions rejected; set equals all component,image,baseline,provider,output-schema,evidence references, including exact digest. No orphan/missing lock entries, digest aliases or self references. Nested models/tuples immutable; validated parameters are not mutable dictionaries. Canonical vectors include nonASCII/escape text and integer edges so Go can match this explicitly named profile (not RFC8785/JCS).
Bound raw input256KiB, decoded depth24 and node budget8192, bounded strings/lists and canonical size; reject duplicates before model conversion, no unbounded recursion/error echo. Use per-call immutable state, no network/DB/locks or global mutable registry; workload is bounded by input limits, no HA/QPS claim. CLI bounded regular-file read (no FIFO blocking), redacted fixed error code and exit2 on bad data, no raw validation input/Token in stderr.
Pure compatibility function checks exact supported Bundle ABI and component descriptor digests supplied by a trusted reader, no version range fallback or automatic upgrade. Only validation support exists in this slice; success report includes validation_only=true and execution_supported=false. Missing/old reader support rejects, but this is not integration with Worker. Unknown future envelope/manifest/ABI/semantic version/component/config errors require explicit new contract; no reinterpretation.

## Compatibility and preservation

Existing agent-definition/1,agent-definition-snapshot/1 and Coverage v1/v2 models/stores/recovery are untouched. No new optional fields, rehash, data rewrite, migration, startup/service changes or new Task admission. Bundle envelope cannot parse as an old Definition and vice versa. Capture committed legacy Definition/Snapshot JSON and digest vectors from baseline and validate them against unchanged code.
CA-P2-01B owns future persistence, publish authorization/CAS/idempotency, immutable v2 Definition/Task binding, asset authenticity/schema/runtime resolution, actual assembly, current authorization, compatible Worker refusal and old Task recovery. It must preserve legacy byte algorithms and Coverage gates. Passing this slice never changes effective Release or descriptor capability.

## Acceptance

Tests: golden positive/canonical/digest/schema/catalog equivalence;20domain completeness; unknown/changed metadata/ABI/config; numeric/Unicode/duplicate/depth/size/type attacks; lock exactness; immutable nested objects; incompatible reader; CLI subprocess/redaction/no I/O side effects; committed legacy v1 golden roundtrip/hash and existing binding/Coverage regressions. Full make test and make check, record pass/skip boundaries and separate offline validation from execution. Source/contract/test evidence hashed; native feature commit/push only, no main integration or production actions.
