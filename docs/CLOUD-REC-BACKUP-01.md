# CLOUD-REC-BACKUP-01 — PostgreSQL logical backup portability

Status: In Progress  
Owner: Codex  
Branch: `codex/cloud-rec-backup-01`  
Owned paths: `tests/compose/recovery_backup/`, `docs/CLOUD-REC-BACKUP-01.md`

## Scope

This child task proves a development-only logical backup path after the
PostgreSQL migration catalog is fully applied. It seeds one deterministic
namespace-scoped Event, creates a non-empty `pg_dump` custom archive, records a
SHA-256 manifest, restores into a fresh database, and compares the migration
catalog, public table names, session-stream count, Event count, and
namespace-scoped Event read.

The runner uses PostgreSQL 17.5 and `pg_dump --format=custom --no-owner
--no-privileges`. It removes its Compose volume and temporary archive on exit.

## Validation

Run from the repository root:

```bash
tests/compose/recovery_backup/run-postgres-tests.sh
```

Acceptance evidence is the sentinel
`ZEBRA_PG_RECOVERY_BACKUP_TEST_RESULT=PASS`, together with the seed and restore
verification lines emitted by the runner.

## Explicit non-goals

- physical base backups, WAL archiving, or point-in-time recovery;
- production credential or object-storage restore;
- disaster-recovery RPO/RTO claims or a production cutover.
