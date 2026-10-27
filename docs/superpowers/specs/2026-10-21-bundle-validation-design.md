# CA-P2-01C — Native scoped Bundle validation

## Dependency and alternatives

Overdoze P2 readiness schedules OD-P2-01A Go draft/CAS/validation intent after a consumable native producer contract. CA-P2-01A published offline bytes/schema/catalog; B added actual immutable Definition/Task assembly through existing Host publisher authority. Neither gives a control-plane service a dedicated pure validation endpoint. Building Go semantics or shelling out to Python would violate the boundary; making a Version solely to validate would mutate native state. Choose a narrow native query/validation prerequisite before Go orchestration. No CA-P3 script runner or deployment work.

## Public protocol

Separate `bundle-validation/1` transport:

- GET `/management/v1/bundle-contract`: authenticated static producer document (existing envelope JSON Schema, exact native component catalog/catalog digest, v1/v2 reader names, Chat/auto/text execution subset and unsupported operations). Return immutable `contractDigest`, configured full Bundle scope, trustRevision and observedAt. It may work without an execution catalog; no execution approval is implied.
- POST `/management/v1/bundle-validation`: raw existing Bundle envelope JSON, max256KiB. Required single `X-Runtime-Bundle-Contract` equals the GET contractDigest. Native parser validates canonical digest/closure/ABI; current private RuntimeExecutionCatalog resolves approved assets and strict RuntimeAssembly. Candidate scope must exactly match credential scope and current catalog scope, including issuer, namespace, product, environment, target and deployment. A valid response binds contractDigest, bundleDigest, assemblyDigest, approvalDigest, scope, trustRevision and observedAt. Worker is not_checked and publication not_performed.

The static document digest covers its content excluding its own digest and transport metadata; preserve the original A artifacts unchanged. An approvalDigest covers public catalog content excluding baseline_key. These receipts are validation facts for a given configuration snapshot, not grants or effective Releases. Go must correlate exact draft revision/input and current target trust before applying evidence; later Version publication must independently revalidate current approvals/authority. Repeating validation is safe because it writes nothing.

## Authentication and isolation

Add optional `ZEBRA_BUNDLE_MANAGEMENT_CONFIG` operator-mounted private JSON file; separate opaque credential prefix `rtbv_` with43URL-safe characters, store only its SHA256. Exact fields: schema_version=`cloud-agent.bundle-management-approval/1`, scope (BundleScope), audience (bounded Identifier), trust_revision1..2^53-1, credential_sha256 lowercasehex64, expires_at UTC string endingZ, actions unique nonempty tuple of bundle.contract.read/bundle.validate. Reject unknown fields; namespace must match actual composition. Read on every call; private regular0400/0600 file, <=16KiB, nonblocking descriptor. No existing credential or automatic action expansion.

Require the existing five single scope headers X-Runtime-Deployment/Audience/Product/Environment/Trust-Revision, matching this explicit approval. Full scope is checked on POST and echoed on GET for consumer correlation. Reject query/cookie/content encoding, duplicate sensitive headers, malformed methods and non-JSON POST. GET body forbidden. Authenticate before exposing any document or validation details. Re-read/re-authorize the private approval immediately before response; require exact approval equality with the initial snapshot, including full scope (issuer/namespace/target), actions and expiry even when token/revision/headers did not change. Never cache old trust, credential or expiry. The execution catalog receipt is a snapshot of the catalog actually resolved, not a promise it remains current; later publication must resolve again. A mounted file alone does not provide globally linearizable multi-replica revocation: replicas must use the operator's shared current source and Go must fence current trust.

## Capacity and errors

Use existing transport idioms and _HEADERS/_error; no new dependency. Async body read <=0.2s and bounded bytes; maximum8inflight operations per instance covers body and background parsing/config reads. Config/validation executes in bounded retained thread slots; caller timeout1s must not release a slot while its thread continues. Retrieve late exceptions, no unbounded retry tasks, no shared mutable validation state. No DB/global lock or remote I/O; replica count multiplies capacity, not an HA/QPS claim.

405 METHOD_NOT_ALLOWED;400 INVALID_ARGUMENT;401 UNAUTHENTICATED;403 SCOPE_MISMATCH/PERMISSION_DENIED;409 CONTRACT_MISMATCH;422 BUNDLE_REJECTED;429 RATE_LIMITED withRetry-After1;503 MANAGEMENT_UNAVAILABLE. Errors contain fixed codes only, never private file paths/keys/profile bodies or Pydantic exception text. Responses no-store. Valid HTTP200 means syntax/semantic/current asset approval only, never Worker/DB readiness, OCI attestation, actual model call or publication.

## Reuse and compatibility

Reuse native schema/catalog/parser/RuntimeAssembly and existing RuntimeExecutionCatalog resolver. Harden that shared catalog file read using a focused private regular bounded nonblocking reader (also used by the new approval loader), avoiding FIFO hangs and unsafe key-file permissions. Legacy target/Host transports and descriptor fields remain unchanged; bundleManagement stays unsupported for persistence/publication, native scripts unsupported. New validation contract explicitly advertises only its read/validation capabilities.

Adding the API-only settings path must not alter the published B HMAC. Exclude only this new non-execution field from baseline_digest; keep all old fields/bytes unchanged. Fixed old settings fixture digest is sha256:c7748ed8d32a5c534d4c7c8290fd71f5d5d3c01d46c3d38c53665a5cce900fdc with key ab*32. Test both None and configured management path; changing old pinned execution settings still changes it. No v1/v2 rewrite or migration.

## Verification

Test native public artifacts and positive/negative vectors against HTTP with no duplicated Go validator. Cover wrong credentials/scopes/actions, disabled config, file modes/nonregular/missing/oversize/duplicate JSON, hostile envelopes and recomputed-digest semantic negatives, unapproved assets, contract mismatch, concurrent isolation, slow body, timeout/cancel slot retention, config rotation during slow validation, no state/provider/tool/Worker effects. Actual loopback subprocess HTTP exercises public configuration/route composition, not TestClient alone. Existing B Worker/Coverage/baseline regressions and full make test/check pass before scoped commit/push. Production/deployment tests remain explicitly unperformed.
