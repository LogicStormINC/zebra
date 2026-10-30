# CLOUD-SAFETY-HEADER-20261030

## Scope and root cause

User authorized resuming the prepared safety-net deployment and unblocking ERP
conversation fsj8f3bttd. Read-only inspection found SSH/HTTPS restored; the machine
uptime exceeded five days. Safety images were already deployed, schema117 was
already applied, and the default Worker configuration was enabled/shadow/max5.
No migration was repeated and no broader source/runtime upgrade was performed.

The actual signed ERP→Native header request returned500. API traceback identified
PostgreSQL UndefinedFunction: MAX(boolean) in the new safety-override join. The
1276-test claim in the supplied handoff did not demonstrate this real SQL path.
The override primary key is(deployment_namespace,session_id), and observation
headers are unique too. Aggregation was unnecessary: use the existing boolean
expression over the unique LEFT JOIN and remove GROUP BY. All task header callers
share this one query. Shadow rows and other namespaces must not terminalize it.

## Validation

- New runnable tests/test_postgres_task_header_safety.py exercises the actual
  production query on real PostgreSQL using connection-private temporary tables,
  then rollback: absent row/override, foreign namespace, failure_count, shadow,
  all3 terminal kinds, missing observation projection. Real gate passed; no
  canonical/business table was modified by this check.
-17 focused safety/command tests passed. One optional PG test skipped locally,
  then explicitly executed against actual PostgreSQL without pytest/fake transport.
- Ruff focused checks and mypy for the changed storage module passed.
- make check stopped at16 inherited size violations. Git HEAD confirms every
  reported file already exceeded500 lines; changed agent_tasks.py decreased from
  518 to515. No unrelated source/ERP fixture/size remediation was attempted.

## Deployment and original Run recovery

Backups, previous Compose/process inventory, immutable build layers and STOP
receipt retained privately at
/opt/erpnext/zebra-agent/safetynet-20261030/header-fix/.
Before recreation: no running full-namespace Session and no current Worker lease.
Only the fixed agent_tasks.py was added to the already-running immutable images:

- API60c4d17d3d976defee7a3cacacced4cd8a5c956389a651c79bbdfc646599fae1.
- Workerc5a894835b636e198ac3674534a7f18adcb0a1be2df32fa798e5b0f345ef9a2a.

Existing env/permissions/secret mounts, high thinking/v2 and shadow mode unchanged.
Signed actual Host header read returned200/statusready/sequence40 after update.
Normal ERP chat.cancel then sent exactly one STOP for existing Task
c9735bf6-314c-4bb1-9ff7-093318431413 / Run
7f210807-ec1f-42da-ac58-01f96fe5a5e1. Native appended sequence41 command,
42turn_cancelled and43session_cancelled. Actual Host snapshot nowcancelled,
messages1 and pending_command false; original Task/Run identities unchanged.
No stream rewrite, replay, direct terminal override or replacement Run was used.
Search/Yahoo/MCP original process identities and restart counts stayed unchanged;
new API/Worker running with0 restarts. Zero new model/search requests.

## Remaining boundary

Safety net remains SHADOW=true: it does not automatically dead-letter other
business Sessions. No actual structural incident was manufactured. Ordinary
model-dialogue acceptance has not been added by this no-model follow-up; no
claim of full production HA/SLO, arbitrary ERP module coverage or auto-recovery
acceptance follows from these checks. This slice completes deployed header
repair and the authorized original-Run STOP, with historical evidence preserved.
