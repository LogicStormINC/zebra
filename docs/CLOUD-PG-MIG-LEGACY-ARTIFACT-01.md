# CLOUD-PG-MIG-LEGACY-ARTIFACT-01

## Artifact legacy export and quarantine evidence

- Status: `In Progress` / implementation slice ready for review
- Date: `2026-08-05`
- Branch: `codex/cloud-pg-mig-legacy-artifact-01`
- Worktree: `/Users/lukeding/Desktop/playground/2026/product/zebra-agent-cloud-pg-mig-legacy-artifact-01`
- Parent: `CLOUD-PG-MIG-LEGACY-CON-01` remains `In Progress`
- Effect/Delivery and Provider continuation successors remain unregistered and inactive.

## Boundary

This child preserves legacy SQLite `artifact_payloads` rows as a deterministic,
manifest-bound quarantine/rebuild input. It does not write
`artifact_payload_metadata`, copy payload bytes, select a deployment namespace,
or activate API, Worker, Runtime, Effect/Delivery or Provider behavior.

## Source-to-target field matrix

| Legacy `artifact_payloads` field | Evidence | Cloud v9 authority conclusion |
| --- | --- | --- |
| `artifact_id`, `session_id`, `kind`, `mime_type`, `sha256`, `size_bytes` | Direct row values | Retain as source evidence; identity and content expectation alone do not authorize a row. |
| `retained_until` | Direct timestamp | Retain as historical value; the target retention check still needs a trusted request timestamp. |
| `created_at` -> `request_created_at` | Direct timestamp, but no request identity | Retain as source evidence; it is not sufficient to authorize a request row. |
| `file_name` | Not present; `access_uri` is not a trusted request name | Unavailable; never inferred from a local path. |
| `pruned_at` -> `pruned_at` | Direct timestamp | Retain as historical value; no `pruning_at`/transition proof exists. |
| `uri` -> `artifact_uri` | Direct string, structurally comparable to `artifact://` | Retain only; it does not prove an Event binding or object receipt. |
| `access_uri` | Direct local file locator | Retain only; payload bytes and object-provider identity are outside this snapshot. |
| `lifecycle_status` -> `lifecycle_status` | Legacy `active`/`pruned` value | Not mapped by name to v9 `staged`/`finalized`/`compensated`/`pruning`/`pruned`. |
| `intended_event_sequence`, `expected_stream_revision` | Not present | Unavailable; never synthesized. |
| idempotency key/hash and request hash | Not present | Unavailable; never synthesized. |
| reservation epoch, fencing token and owner | Not present | Unavailable; never synthesized. |
| `reserved_at`, `updated_at` | Not present as trusted authority timestamps | Unavailable; migration defaults cannot be treated as history. |
| Event id/sequence and lifecycle revisions/timestamps (`event_id`, `event_sequence`, `lifecycle_revision`, `finalized_at`, `compensated_at`, `pruning_at`) | Not present | Unavailable; never synthesized. |
| object version and verification time | Not present | Unavailable; never synthesized. |
| deployment namespace | Not present | No namespace is inferred from `session_id` or local configuration. |

## Quarantine contract

`migration_legacy_artifact.py` writes a versioned `manifest.json` plus canonical
`records.jsonl`. The manifest binds the source snapshot manifest digest, source
table, row count and row digest, and records the unavailable-field reason
`missing_cloud_authority_bindings` with disposition
`quarantine_rebuild_required`. Loading verifies the manifest digest, row
checksum, row shape, source table and canonical ordering before a rebuild can
be considered.

The original SQLite snapshot remains the source of truth. The quarantine is an
additional review/rebuild input, not a temporary PostgreSQL authority table.

## Validation

- Focused local matrix covers deterministic ordering, round-trip loading,
  tamper rejection and missing-source rejection.
- The isolated runner is
  `tests/compose/migration_legacy_artifact/run-postgres-tests.sh`; it starts
  PostgreSQL `17.5-alpine3.21`, runs the focused test file, requires
  `ZEBRA_PG_MIG_LEGACY_ARTIFACT_TEST_RESULT=PASS`, and removes its container,
  volume and network.
- The PostgreSQL preflight rejects a snapshot containing `artifact_payloads`
  before Event writes and asserts zero rows in both `session_events` and
  `artifact_payload_metadata`; the quarantine remains loadable afterward.

## Closeout rule

Move this child to `Review` only after the focused tests, strict static checks,
runner cleanup and `git diff --check` pass on this branch. `Done` requires
independent review and does not unlock the parent migration or activate the
Effect/Delivery or Provider successors.
