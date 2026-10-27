# Native script package validation /1

Producer: CA-P3-01C, based on published CA-P3-01B60893da8. This is an additional
scoped HTTP contract; all A/B/P2 producer artifacts retain their original bytes.

- contract.json: exact discovery document and canonical integer/ASCII digest, excluding only contractDigest.
- request.schema.json: strict byte-preserving envelope; six-field scope and canonical standard Base64.
- response.schema.json / openapi.json: successful observation, fixed errors and public transport.
- positive-vectors.json / negative-vectors.json: one exact raw request and twelve refusal vectors,
  exercised through the actual native adapter and independent socket consumer.
- prior-artifacts.json: predecessor identities, sorted relative-path/NUL/bytes/NUL directory SHA256;
  normal tests need neither another checkout nor Git history.

Response schema references request.schema.json locally; retain both when vendoring.
A successful syntax/digest check does not import/execute source, approve dependencies,
attest publisher trust, verify Worker readiness, create build/Eval evidence or certify Coverage.
See [operational contract](../../SCRIPT_VALIDATION.md) for credentials, limits and scope.
