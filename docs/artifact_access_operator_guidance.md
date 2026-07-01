# Artifact Access Operator Guidance

## Purpose

This runbook explains how to interpret denied versus unavailable artifact
responses in local Zebra Agent operator flows.

## Response Classes

### `artifact_access_denied`

Meaning:

- the artifact exists as a readable surface
- the current session policy profile is below the required access threshold

Typical examples:

- `workspace_write` session reading a `sensitive` artifact
- any non-`full_access` session reading an access class that resolves to
  `required_policy_profile=full_access`

Operator action:

1. Inspect the response `access` block.
2. Compare `session_policy_profile` with `required_policy_profile`.
3. Re-run the session under a stronger local policy profile only when the
   repository task and operator intent justify the escalation.

Do not treat this as a storage failure. It is a policy decision.

### `artifact_unavailable`

Meaning:

- the access policy allows the read path, but the payload is not retrievable

Typical examples:

- `artifact_is_indexed_only`
- `artifact_payload_missing`
- `artifact_payload_pruned`
- `artifact_uses_external_reference`

Operator action:

1. Inspect the `reason` field.
2. If the payload is missing or pruned, decide whether the artifact should be
   regenerated.
3. If the artifact is indexed-only or external, use the metadata or upstream
   source instead of expecting local payload bytes.

Do not escalate policy for an unavailable payload. Policy is not the blocker.

## Access Metadata

Artifact read responses may include an additive `access` block with:

- `class`
- `required_policy_profile`
- `session_policy_profile`
- `allowed`

Interpretation:

- `allowed=true` means policy is not blocking the read
- `allowed=false` means the request is denied by policy before payload
  retrieval matters

## Local Escalation Guidance

Use `full_access` only when both are true:

- the artifact is intentionally sensitive and must be inspected
- the local task requires human-reviewed access to its content

Prefer keeping routine artifact inspection at `workspace_write` when possible.
