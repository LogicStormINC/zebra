# CLOUD-REC-RESTORE-01 — fresh-instance restore and rebuild

Status: Done  
Owner: Codex  
Branch: `codex/cloud-rec-restore-01`  
Owned paths: `tests/compose/recovery_restore/`, `docs/CLOUD-REC-RESTORE-01.md`

## Scope

This child proves a development-only recovery composition after the migration
and logical-backup gates. PostgreSQL 17.5 is restored into a fresh `template0`
database. An S3-compatible MinIO object is explicitly deleted and rebuilt from
its SHA-256/size manifest. Redis is flushed and rebuilt by replaying the
restored namespace Event through the existing live fan-out adapter. Finally,
the restored control-plane epoch is rotated and a new lease fence is acquired
before release.

The runner never enables API/Worker cloud writes and does not make physical
PITR/WAL, production credentials, retention, RPO/RTO, failover or DR claims.

## Validation

Run from the repository root:

```bash
tests/compose/recovery_restore/run-recovery-tests.sh
```

Acceptance evidence is the sequence of `RECOVERY_RESTORE_*` `PASS` lines and
the final sentinel `ZEBRA_PG_RECOVERY_RESTORE_TEST_RESULT=PASS`. The runner
removes its PostgreSQL/Redis/MinIO volumes, network and temporary files on exit.

Validation completed on 2026-08-05:

- `RECOVERY_RESTORE_SEED=PASS migrations=16 events=1 lease_token=1`;
- `RECOVERY_RESTORE_ARCHIVE=PASS` for a non-empty 159,998-byte logical archive;
- `RECOVERY_RESTORE_CLEAR=PASS artifact=absent redis=flushed`;
- `RECOVERY_RESTORE_VERIFY=PASS migrations=16 events=1` with a fresh Artifact
  version and a new control-plane epoch/fence;
- `ZEBRA_PG_RECOVERY_RESTORE_TEST_RESULT=PASS` with deterministic cleanup.
