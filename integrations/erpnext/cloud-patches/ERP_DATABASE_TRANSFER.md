# ERP105 transfer operator

Source prepared, **not authorized by this file to execute a production transfer**. No infrastructure creation, service stopping, configuration activation, native migration or consumer release is implemented. Transfer success means `verified_unactivated`; original ERP consumers must remain stopped. Trench stays on the original105 server.

`transfer_erp_database.py` runs with host Python stdlib and the local pinned105 API image's existing psycopg. It creates one temporary plain Python maintenance container, joins the two verified networks, and removes that container and its credential copy on exit. It never starts API/Worker/scheduler code. No dependency installation, image pull, source writes, source `nextval`, trigger disabling or replication-role bypass occurs.

## Protected inputs

Run as the owner of the protected inputs. Configuration, operator gate evidence and approved inspection files must be regular `0600` files in owned `0700` directories. The evidence directory must already exist, owned by the operator with mode `0700`. The script creates a separate private run directory for each invocation. Keep server-side files protected; never print the config, compose, DSNs, native SQL errors or row contents.

Production configuration keys (no scope override exists):

```json
{
  "source": {"host": "<actual original container IP>", "port": 5432, "dbname": "zebra", "user": "zebra", "password": "<protected source credential>"},
  "destination": {"host": "<actual new container IP>", "port": 5432, "dbname": "<dedicated ERP database>", "user": "<dedicated nonsuperuser owner>", "password": "<protected runtime credential>"},
  "destination_container": "<new ERP-only PostgreSQL container>",
  "destination_network": "<new ERP-only network>",
  "destination_volume": "<new named data volume>",
  "evidence_directory": "/absolute/protected/evidence",
  "gate_evidence": "/absolute/protected/gate.json",
  "gate_sha256": "<SHA256 of exact gate.json bytes>"
}
```

Connection objects allow only `host`, `port`, `dbname`, `user`, `password`, `sslmode`. Connection identity uses native PostgreSQL `host(inet_server_addr())`, preserving strict equality with the actual Docker-inspected server IPs without an inet `/32` mask; use a unique destination alias in the later runtime configuration. The tool verifies original source identity, distinct server/database/owner, exact17.5 image, locale, volume, network and absence of target ports/consumers. It checks effective owner privileges/memberships, absence of the destination role on the original server, and an actual authentication attempt with destination credentials at the original endpoint. Connectivity errors alone are insufficient authentication evidence. Local native `pg_dump`/`psql` uses trusted container Unix sockets as OS user `postgres`; `psql -w` refuses an unexpected password prompt. It never passes passwords or complete DSNs in argv or environment arguments. Source has no database role named `postgres`.

The source fixed tables cover 138 base tables and one view, plus exact inventories of 35 native functions, 78 noninternal triggers and four owned sequences. Inspection captures full column/type/order/default/generated/identity/collation, table options, PK/FK/check/index/view definitions, function bodies/security/volatility/settings and trigger definitions/enabled/constraint state. Native functions/triggers are restored by pg_dump pre/postdata, including their original deferred/constraint semantics. Source has no SECURITY DEFINER functions. Unknown objects or a changed approved manifest fail closed.

Gate JSON version1 must contain:

```json
{
  "version": 1,
  "reviewed_by_operator": "<reviewer identity>",
  "site": "erpnext.zebra.local",
  "observed_at": "<fresh timezone-aware ISO timestamp>",
  "guard_source_commit": "<40-character deployed Host commit>",
  "admission_probe": {"http_status": 417, "cloud_mutations": 0, "response_sha256": "<response digest>", "evidence_ref": "<protected actual authenticated rejected-submit probe>"},
  "conversation_lock_drain": {"outstanding": 0, "checked": 9, "evidence_ref": "<actual all-conversation lock drain evidence>"},
  "producer_inventory": [{"identity": "<exact deployed container/process ID>", "kind": "worker", "state": "stopped", "evidence_ref": "<actual inventory record>"}],
  "unresolved": []
}
```

The probe accepts the actual maintenance rejection status409/417/423/503. All producer inventory entries must identify actual stopped/disabled processes. Refresh evidence within30minutes and cover autonomous producers, not only browser submit. This artifact is **operator-reviewed external attestation**, explicitly reported as such, not independent proof of Host locks/process coverage. A boolean does not establish the gate. The tool independently verifies exact source API/Worker stopped, no destination-network consumers, empty command/inbox/broker/shadow queues, zero schedules/firings, released leases, terminal succeeded effects and acked handoffs. All138 scoped table hashes form the queue/idempotency/lease/Task/segment/receipt baseline. Fresh separate source read-only transactions compare every hash before target mutation and after verification, detecting writes hidden from the exported snapshot. Unknown producers/unresolved evidence blocks transfer.

## Inspection, review and transfer

```sh
python3 transfer_erp_database.py inspect /protected/config.json
# Review the protected inspection.json: complete catalog, exact105 migration
# checksums, selected scopes and all full-row counts/hashes. Preserve its bytes.
python3 transfer_erp_database.py transfer /protected/config.json \
  --approved /protected/inspection.json --fingerprint <printed inspection-file SHA256>
```

Inspection never restores or copies target data; it still performs endpoint/container checks and uses a temporary maintenance container. Its fresh snapshot ID is metadata; approval compares the full manifest/hashes, not equality of two different exported snapshot IDs. Allowed deployment namespaces are exactly `erpnext`, `erpnext-history`, `erpnext-continuation`; empty history/continuation namespaces are allowed. Definition tables require exactly `namespace_id='erpnext' AND authority_issuer='https://erpnext.zebra.local'`. No prefix or arbitrary namespace expansion is accepted. FK closure must already hold for selected rows. Before any destination mutation, every source version/name/checksum triple must equal the installed pinned105 native `MIGRATIONS` catalog and its pure `Migration.checksum` property. No migration runner/bootstrap is called. A plausible but changed checksum/name/version fails even if the source-derived approval contains it. The unchanged full105 migration ledger is copied.

One read-only repeatable source snapshot and ACCESS SHARE locks stay open through both native schema dumps, text COPY and verification. Both dumps use that exported snapshot. The target empty `public` schema is dropped with `RESTRICT` inside the same pre-data restore transaction, then recreated by unchanged native DDL. Native `psql -X -w -v ON_ERROR_STOP=1 --single-transaction` restores pre/postdata as the dedicated owner. Cyclic FKs validate after COPY; no triggers are bypassed. Generated columns are excluded from COPY and included in canonical full-row hashes. Explicit nongenerated columns preserve identity values. Native text COPY bytes stream directly between psycopg connections; only metadata crosses NDJSON.

Sequences initialize from preserved maximum owned-column values without consuming `nextval`; empty tables use start1/is_called=false, and exhausted bounds fail. Exact target structure, all counts/hashes, generated output, scopes, migrations and fresh source baseline must agree. That comparison includes every original Task/Run/event/binding/receipt identity and payload. No rows or table contents enter logs/reports.

Failure leaves `INCOMPLETE.json` and an unactivated target. Pre-data, data, post-data and sequences are separate durable phases; the tool never claims whole-transfer rollback. Cleanup status records whether temporary-container absence was actually proven. A Docker removal or attach-process termination failure writes `CLEANUP_INCOMPLETE.json`, preserves the original transfer failure, and still attempts credential-copy deletion; it never claims successful container removal after an error. Raw native errors remain only in protected diagnostics. User-facing errors expose bounded phase/reason/SQLSTATE. Do not retry into a nonempty target, blindly recopy queues, reconnect source consumers or erase original ERP data. A failed worker/protocol/snapshot ends this attempt.

Configuration cutover, pinned105 API-only continuity reads, exact grant-audit/JTI first-write evidence and no-execution comparison remain separate reviewed root operations. The105 API schema check is read-only and lifespan only warms JWKS; start API alone with admission paused and producers absent. The105 Worker remains a database consumer even with Rabbit disabled, performs projection/memory maintenance and may invoke a memory-title model; never start it for readiness. Every consumer release requires the legacy observation-only behavior, private quota and fresh-authority safeguards to have completed review and actual acceptance. Keep Worker/other consumers stopped through the separate106 upgrade and acceptance; do not start105 Worker before that upgrade. The explicit one-time release is a later root operation. After destination writes, rollback requires reconciliation. Schema106 is outside this operator.

## Runnable checks and isolated QA

```sh
python3 check_transfer_erp_database.py
```

Default checks use no database writes. Run the same file in the exact pinned API image for actual psycopg identifier quoting/value separation checks. They cover fixed inventories/scopes, unknown relations, PK/generated/partition/view/function/trigger changes, version/checksum/count/hash approval changes, invalid constraints/indexes, privileged/wrong/nonempty targets, membership/source-role rejection, read-only inspection phase routing, secret redaction, file permissions, sequence emptiness/exhaustion and COPY rollback without activation.

`--disposable-qa` exercises the same full105 operator on root-created isolated QA endpoints. Its config replaces `gate_evidence`/`gate_sha256` with `qa_source_container`/`qa_source_network`. It requires:

- Both PostgreSQL containers carry `zebra.erp.qa=database-transfer`, use the exact pinned17.5 image and distinct volumes.
- Container names begin `erpnext-db-qa-source-` and `erpnext-db-qa-target-`.
- Source database begins `zebra_transfer_qa_source_`; destination begins `erpnext_agent_qa_`.
- Both join the same internal network beginning `erpnext-db-transfer-qa-`; only the two databases and maintenance container may join.

The QA network absence check replaces the external Host/production-service gate only for these explicit disposable identities. Fixed ERP scopes, complete105 schema, role/auth isolation, hashing and every restore rule remain identical. Root must bootstrap SOURCE QA from the actual pinned105 native migration catalog through a maintenance entrypoint only, then seed synthetic ERP rows and inspect/review/transfer. Never use newer107 code, application workers or original source data. No QA DDL has been executed by these source checks.

A separate small native roundtrip fixture is included in `check_transfer_erp_database.py` and deliberately does **not** satisfy the production105 catalog inventory. Have root create additional empty QA databases on the labeled QA servers (source name `zebra_transfer_qa_source_fixture_*`, target `erpnext_agent_qa_fixture_*` owned by the dedicated runtime role); do not reuse a partially loaded full105 target. A protected fixture config contains only `source` and `destination` psycopg connection objects using those database names.

Run each fixture phase in a temporary pinned105 API container, with plain `/app/.venv/bin/python`, matching host file-owner UID/GID, the QA internal network and protected read-only mounts for this script, the operator module and config. No Docker socket or native application entrypoint is required:

Before any fixture DDL, run `check_transfer_erp_database.py --fixture identity /protected/fixture.json` with actual Docker server IPs in the config. This opens only read-only identity transactions, executes the real native identity SQL on both PostgreSQL17.5 servers, and requires exact address/database/role matches. It may also run against already-seeded full105 QA databases.

1. `check_transfer_erp_database.py --fixture prepare /protected/fixture.json` creates three tiny QA source tables, a view, escaped text/literal NULL marker/SQL NULL, Unicode JSON, a timezone timestamp, preserved identity values, a generated column, cyclic deferred FKs and empty/nonempty owned sequences. This is explicitly write-enabled QA bootstrap and must be invoked by root.
2. Root uses source QA container native `pg_dump --schema-only --schema=public --no-owner --no-acl --section=pre-data` and `--section=post-data` to protected files. The fixture source is static and closed between phases; this small fixture does not establish the full operator's held-snapshot gate. Root restores pre-data with `DROP SCHEMA public RESTRICT` and unchanged native dump in one dedicated-owner `psql --single-transaction`.
3. `--fixture copy /protected/fixture.json` injects a failure after the first table's COPY and proves zero committed rows, then runs the production COPY transaction path and compares all full-row hashes.
4. Root restores unchanged native post-data with `ON_ERROR_STOP`/one transaction; cyclic FKs must validate.
5. `--fixture verify /protected/fixture.json` verifies native constraints/indexes, full-row hashes/identity/NULL/text/JSON/timestamp preservation, changes **only the generated expression** in a rolled-back transaction to prove generated output participates in hashing, and verifies empty/nonempty sequence initialization without `nextval`.

This fixture is not production acceptance. The full105 disposable transfer, actual restore/authentication/locale checks, native Host guard activation/probes and production cutover remain pending until root executes and records them.
