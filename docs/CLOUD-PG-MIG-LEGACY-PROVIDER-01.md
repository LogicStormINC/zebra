# CLOUD-PG-MIG-LEGACY-PROVIDER-01

## Provider Continuation legacy export and quarantine evidence

- Status: `Done` / independently reviewed and merged into the parent migration
- Date: `2026-08-05`
- Branch: `codex/cloud-pg-mig-legacy-provider-01`
- Worktree: `/Users/lukeding/Desktop/playground/2026/product/zebra-agent-cloud-pg-mig-legacy-provider-01`
- Parent: `CLOUD-PG-MIG-LEGACY-CON-01` remains `In Progress`
- Provider authority predecessor: `CLOUD-PROVIDER-CONT-PG-01` is `Done`
- Parent merge: `ce8880c0` on `codex/cloud-pg-mig-01`

## Boundary

This child preserves legacy SQLite `provider_continuation_artifacts` rows as a
deterministic, manifest-bound quarantine/rebuild input. It does not write the
v13 PostgreSQL Provider Continuation authority, transfer opaque payload bytes,
or activate API, Worker, Runtime or Provider behavior.

## Source-to-target field matrix

| Legacy `provider_continuation_artifacts` field | Evidence | Cloud v13 authority conclusion |
| --- | --- | --- |
| `artifact_id` -> candidate `continuation_id` | Direct local identifier; structurally comparable only | Retain as source evidence; without namespace and scope it is not a cloud identity. |
| `tenant_id` | Direct local tenant value | Retain unchanged; it cannot be promoted to `deployment_namespace`, `authority_issuer` or `namespace_id`. |
| `session_id` | Direct session value | Retain as source evidence; the legacy row does not bind it to a cloud namespace or selection Event. |
| `reference_id`, `provider`, `model_name`, `capability_version`, `source_hash` | Direct reference metadata | Retain as structurally comparable metadata; uniqueness and authority scope cannot be reconstructed. |
| `opaque_payload`, `payload_sha256`, `size_bytes` | Direct bytes/digest/size | Retain in quarantine only; no opaque payload transfer or new cloud receipt is authorized. |
| `created_at`, `expires_at`, `deleted_at` | Direct lifecycle timestamps | Retain as historical values; target lifecycle revision and Event-backed transition history are unavailable. |
| `deployment_namespace` | Not present | Unavailable; never inferred from `tenant_id` or local configuration. |
| external authority identity (`authority_issuer`, `namespace_id`) | Not present | Unavailable; provider metadata cannot establish the trusted cloud scope. |
| lifecycle revision | Not present | Unavailable; migration defaults cannot be treated as historical authority. |
| continuation selection Event (`selection_event_id`, `selection_event_sequence`) | Not present | Unavailable; existing Event payloads are not used to fabricate a binding. |
| idempotency and request identity (`idempotency_key`, `request_hash`) | Not present | Unavailable; never synthesized from artifact/reference fields. |
| accepted LeaseFence (`accepted_lease_epoch`, `accepted_lease_fencing_token`, `accepted_lease_owner_instance_id`) | Not present | Unavailable; no Worker acceptance or fence is invented. |
| mutation/audit history | No legacy tables or rows | Unavailable; `provider_continuation_mutations` and management audit cannot be reconstructed. |

## Quarantine contract

`migration_legacy_provider.py` writes a versioned `manifest.json` plus canonical
`records.jsonl`. The manifest binds the source snapshot manifest digest, source
table, row count and row digest, and records the unavailable-field reason
`missing_cloud_authority_bindings` with disposition
`quarantine_rebuild_required`. Loading verifies the manifest digest, row
checksum, row shape, source table and canonical ordering before a rebuild can
be considered. Non-finite JSON values are rejected at the load boundary.

The original SQLite snapshot remains the source of truth. The quarantine is an
additional review/rebuild input, not a temporary PostgreSQL Provider authority
table.

## Validation

- Focused local matrix covers deterministic ordering, byte-preserving
  round-trip loading, tamper rejection, non-finite JSON rejection and
  missing-source rejection.
- The isolated runner is
  `tests/compose/migration_legacy_provider/run-postgres-tests.sh`; it starts
  PostgreSQL `17.5-alpine3.21`, runs the focused test file, requires
  `ZEBRA_PG_MIG_LEGACY_PROVIDER_TEST_RESULT=PASS`, and removes its container,
  volume and network.
- The PostgreSQL preflight rejects a snapshot containing
  `provider_continuation_artifacts` before Event writes and asserts zero rows
  in both `session_events` and the target Provider authority; the quarantine
  remains loadable afterward.

## Closeout

Independent review found no blocking SQL, deserialization, authority-boundary
or cleanup issue. The child was merged into `codex/cloud-pg-mig-01` at
`ce8880c0` after the post-merge focused matrix, strict static checks, runner
cleanup and `git diff --check` passed. This closes the child as `Done`; it does
not close the parent migration or modify the completed Provider authority
implementation.
