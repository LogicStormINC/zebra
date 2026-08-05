# CLOUD-PG-MIG-LEGACY-EFFECT-DELIVERY-01

## Effect/Delivery legacy export and quarantine evidence

- Status: `In Progress`
- Date: `2026-08-05`
- Branch: `codex/cloud-pg-mig-legacy-effect-delivery-01`
- Worktree: `/Users/lukeding/Desktop/playground/2026/product/zebra-agent-cloud-pg-mig-legacy-effect-delivery-01`
- Parent: `CLOUD-PG-MIG-LEGACY-CON-01` remains `In Progress`
- Artifact predecessor: `Done` and merged into `codex/cloud-pg-mig-01`
- Provider continuation remains unregistered and inactive.

## Boundary

This child preserves legacy SQLite `effect_ledger` rows as a deterministic,
manifest-bound quarantine/rebuild input. It does not write `effect_outbox`,
transfer external-effect results, or activate API, Worker, Runtime,
Effect/Delivery or Provider behavior.

## Source-to-target field matrix

| Legacy `effect_ledger` field | Evidence | Cloud v3 authority conclusion |
| --- | --- | --- |
| `root_session_id` | Direct row value | Retain as historical source evidence; it does not identify an execution session or namespace. |
| `ledger_key` | Direct row value | Retain as a legacy key; it does not prove dispatch identity, retry identity or the target uniqueness scope. |
| `identity_json` | Direct JSON; may be structurally comparable to `EffectIdentity` | Retain unchanged; an identity shape does not prove request binding, payload binding or accepted authority scope. |
| `attempt` | Direct integer | Retain as historical attempt evidence; no target request/retry contract is established. |
| `status` | Legacy `reserved`, `executing`, `succeeded`, `failed_no_effect`, `uncertain` values | Names overlap only partially with v3; no value maps without intent/terminal Events, claim fencing and terminal evidence. |
| `result_json` | Direct value only for some legacy terminal rows | Retain as opaque source evidence; it cannot become target `result` without the intent/terminal Event and payload binding. |
| `created_at`, `updated_at` | Direct timestamps | Retain as historical values; target timestamps and lifecycle transitions cannot be reconstructed from them. |
| `deployment_namespace` | Not present | Unavailable; never inferred from `root_session_id` or local configuration. |
| dispatch, execution and retry identity (`dispatch_id`, `execution_session_id`, `retry_key`) | Not present | Unavailable; never synthesized. |
| request and payload binding (`request_hash`, `payload_artifact_ref`) | Not present | Unavailable; no external-effect request is reconstructed. |
| claim Lease/Fence (`claim_epoch`, `claim_fencing_token`, `claim_owner_instance_id`, `claim_expires_at`) | Not present | Unavailable; no Worker claim or fencing fact is invented. |
| intent/terminal Event bindings (`intent_event_id`, `terminal_event_id`) | Not present | Unavailable; the Event stream is not used to fabricate effect authority. |
| terminal evidence (`evidence`, `evidence_history`) | Not present | Unavailable; status and result text are not delivery evidence. |

## Quarantine contract

`migration_legacy_effect.py` writes a versioned `manifest.json` plus canonical
`records.jsonl`. The manifest binds the source snapshot manifest digest, source
table, row count and row digest, and records the unavailable-field reason
`missing_cloud_authority_bindings` with disposition
`quarantine_rebuild_required`. Loading verifies the manifest digest, row
checksum, row shape, source table and canonical ordering before a rebuild can
be considered. Non-finite JSON values are rejected at the load boundary.

The original SQLite snapshot remains the source of truth. The quarantine is an
additional review/rebuild input, not a temporary PostgreSQL Effect/Delivery
authority table.

## Validation

- Focused local matrix covers deterministic ordering, round-trip loading,
  tamper rejection, non-finite JSON rejection and missing-source rejection.
- The isolated runner is
  `tests/compose/migration_legacy_effect/run-postgres-tests.sh`; it starts
  PostgreSQL `17.5-alpine3.21`, runs the focused test file, requires
  `ZEBRA_PG_MIG_LEGACY_EFFECT_DELIVERY_TEST_RESULT=PASS`, and removes its
  container, volume and network.
- The PostgreSQL preflight rejects a snapshot containing `effect_ledger`
  before Event writes and asserts zero rows in both `session_events` and
  `effect_outbox`; the quarantine remains loadable afterward.

## Closeout

Pending independent review, PostgreSQL runner evidence and parent merge. This
child does not close the parent migration or activate Provider continuation.
