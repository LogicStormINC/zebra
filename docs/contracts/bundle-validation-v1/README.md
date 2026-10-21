# Native Bundle validation producer artifacts

- `contract.json`: exact `native_bundle_contract()` document. Its `contractDigest`
  uses Bundle v1 integer/ASCII canonical JSON and excludes only that field.
- `openapi.json`: scoped HTTP transport. External request/scope schema references
  point to the unchanged sibling `../runtime-bundle-v1/envelope.schema.json`.
  Consumers vendoring this contract must retain that sibling schema or explicitly
  bundle its references. GET also carries the complete original schema/catalog.
- `positive-vectors.json`: raw approved Chat/auto/text envelope, public execution
  catalog without its private key, expected Bundle/assembly/approval digests.
- `negative-vectors.json`: raw HTTP inputs and expected status. Semantic negatives
  recompute the outer digest, so a stale hash cannot mask the intended refusal.

These are native-owned artifacts for a Go adapter, not Go validation semantics.
Vectors use synthetic approvals and contain no usable credential or private key.
The positive public catalog alone cannot authorize a service. Independent public
contract and actual HTTP process tests are in `tests/test_bundle_management_contract.py`
and `tests/api/test_bundle_management_process.py`. See `docs/BUNDLE_MANAGEMENT.md`
for scope, capacity, evidence correlation and publication limitations.
