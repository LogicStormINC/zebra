# Native Plugin product admission / 1

Authoritative producer artifacts for CA-P4-01. See ../../CA-P4-01_plugin_admission.md.
JSON schemas describe wire shape; Native integrity validation and shared current
approval remain authoritative. Never treat schema validation as package approval.

GET /management/v1/plugin-admission/contract returns the contract. POST
/management/v1/plugin-admission uses action validate or publish. GET the same
admission path with exactly one X-Runtime-Operation or X-Runtime-Plugin-Digest
selector returns the original receipt/current approval. Without selectors GET
returns the contract. Cookie/query credentials are forbidden. Send the exact
X-Runtime-Plugin-Contract contractDigest for all non-contract operations, including GET.
All routes require a separate rtpa_ Bearer credential and exact current management
scope headers (deployment, audience, product, environment, trust revision).

validate accepts sorted files with strict base64 preserving exact uploaded bytes;
the caller unwraps its already bounded structural ZIP. No archive extraction or
code import occurs in Runtime. Root plugin.json must be 0.2; root README.md is
hashed documentation; all other content must belong to declared Skill components.

publish accepts an original canonical UUID and exact Native package_digest, never
archiveDigest or platform inventory digest. It reads only the operator-approved
read-only directory <bundle_root>/<Native digest without sha256:>. The current
product approval must list that digest. It does not remotely upload, install,
issue grants or execute. The operator staging requirement is explicit: a valid
platform ZIP alone cannot grant trusted source publication.

A committed original receipt has contractVersion, full scope, operationId,
inputDigest (exact request bytes), packageDigest and the immutable PluginPackagePin.
GET separates originalResult from currentApproval. Revoked packages retain old
receipts/pins; false currentApproval is not a rollback or cancellation proof.
Missing receipts and timeouts are unknown, never permission to resend POST.
