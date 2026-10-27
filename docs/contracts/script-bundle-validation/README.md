# Pure ScriptBundle validation / 1

Producer: CA-P3-01E. `contract.json` embeds the exact native `request.schema.json`.
`vectors.json` separates JSON Schema admission from native parser semantics:
`schemaValid` can be true while `nativeParseValid` is false (digest mismatch).
A static consumer schema checker must not claim to have implemented Python digest,
closure, catalog approval, Worker, publication, execution or Coverage semantics.

GET `/management/v1/script-bundle-contract`, POST `/management/v1/script-bundle-validation`.
Both require scoped `rtbv_` private approval; the two `script-bundle.*` actions
must be explicitly granted. Existing `bundle.*` actions and old contracts do not expand.
POST requires `X-Runtime-Script-Bundle-Contract` equal to this artifact's digest.
The request is the raw, bounded ScriptBundle, with no upload/source or persistence side effect.

Positive parser vectors are illustrative declarations, not operator-approved assets.
Only the independent API tests provision private catalog/2 and prove live pure observations.
Responses bind raw input, complete scope/trust/time, outer/base/assembly/catalog digests,
while Worker/publication/persistence/source execution remain explicitly unchecked/unperformed.
