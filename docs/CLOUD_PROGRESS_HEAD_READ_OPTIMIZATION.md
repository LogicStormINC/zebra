# Bounded single-statement Worker progress reads

Task `PROGRESS-HEAD-READ-01`, owner Luke Ding, executor Codex.
Branch `codex/progress-head-read-01`, base `157d13c9`.

## Measured cause and minimal implementation

The shared `WorkerProgressStoreMixin._progress_head` reads one checkpoint in two
statements: identity/size metadata, then state JSON/frontier. Its four callers are
checkpoint restore, indexed output membership, indexed receipt membership, and
atomic progress advancement. Their current production consumers are Worker
progress recovery; API has no caller of these four methods.

The repository already solves this problem in `execution_inputs._head`. Reuse
its SQL CASE and native UTF-8 byte length pattern, without a new helper or Port.
A single statement returns scalar metadata and returns JSON only if declared
size is 1..32768 and equals actual bytes. Python still validates scope, byte
identity, state schema and frontier. PostgreSQL uses octet_length; SQLite uses
length(CAST(state_json AS BLOB)), preserving multibyte behavior.

Only one production function changes. No cross-call cache, pool, dependency,
schema, deadline, retry, projection-write ordering or authority change. Initial
missing heads remain explicit; Run validation, locking, canonical source
verification, CAS, dedup and fresh publication ownership remain unchanged.

## Native comparison

One disposable PostgreSQL server, four A/four B in ABBA/ABBA order with fresh
independent namespaces/epochs. A replaces only _progress_head with the original
from157d13c9; B uses candidate. Same fenced response/commentary operation as the
previous slice, excluding setup. Count explicit cursor SQL/TaskIO connect calls;
no SQL text, credentials, prompts or body payloads are retained in receipts.

| Median per response/commentary operation | Original A | Candidate B |
| --- | ---: | ---: |
| SQL calls | 57 | 55 |
| TaskIO connections | 9 | 9 |
| Bounded event pages | 2 | 2 |
| Native elapsed | 254.52 ms | 255.77 ms |

Two fewer queries equal3.5% of this operation. There is no measured stable
latency improvement; connection count is unchanged. Do not extrapolate to
whole-Run/startup SQL, browser first body or SLA. Both modes complete all eight
ordinary cases with exactly one commentary output and no pending gap.

Fault control delays only the old second body SELECT using pg_sleep(3). Original
stops at1827.47ms with confirmed-source checkpoint timeout/output0; candidate
issues no second SELECT and completes235.56ms/output1 within unchanged2s scope.
This removes one failure opportunity, not necessary-read/database-outage risk.

## Validation and rollout boundary

Default `check_progress_risk_boundaries.py` now uses real in-memory SQLite to
assert one query, absent/initial heads, multibyte byte sizes, exact32KiB boundary,
invalid size metadata, and oversize/misreported bodies never crossing the DB
hydration boundary. It fails the original with two-query assertion before source
edit. Existing missing-head test keeps no-write/no-SELECT-star assertions and
checks a single head query instead of forbidding the state_json column name.
This is the only existing assertion changed; no fixture/schema repair.

- Existing SQLite/core/recovery/commentary regressions:74passed.
- Existing native PostgreSQL progress/concurrent-CAS/Run identity/commentary/
  unknown acknowledgement/lease fence regressions:11passed.
- Native PostgreSQL temporary-table controls cover missing/initial, Unicode,
  exact32KiB, dishonest/oversize body and foreign scope, with zero invalid body
  bytes returned. Temporary table shadows only this connection's name.
- Clean tracked-source `make check` passes: file-size3094, whole-source Ruff,
  mypy1283, eval30 and both standalone no-model fault gates. Private historical
  diagnostic artifacts are excluded by the same clean-export process as prior
  slices; no lint configuration or unrelated fixture edits.
- Final source-only Worker5f2b9889 is healthy/zero restarts.79retained/replaced
  source identities and original six Compose/environment/commands/search checks
  pass. API907fcc00 retains its exact image/start timestamp. Overlay digest
  matches current source. Current consumers are Worker-only, so API was not
  replaced; any future image build receives the shared source normally.
- Zero active Host intents checked before activation. No model call, historical
  Run replay, page acceptance, push, npm publication or remote deployment.

Private counts/logs/rollout receipts: `.artifacts/progress-head-20261016/`.
