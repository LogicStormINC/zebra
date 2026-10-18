# TRN-ASSET-RECOVERY-01: historical asset recovery

## Result and boundary

The local signed-in asset page again lists 14 retained Agent files and three
saved reports. All 14 browser download requests returned HTTP 200. Native signed
reads verified every payload length against its delivery metadata and recorded
SHA-256 checksums. Ten supported JSON/PNG/JPEG files also passed HEAD and byte
Range checks; SVG and the legacy image/jpg alias retain their existing preview
format restrictions. PNG preview decoded at 2239 x 1337. JSON text preview works;
this acceptance does not claim a Vega v5 JSON file was rendered as a chart.

## Root causes and repair

- Trench previously scanned every current conversation Task (371 at diagnosis),
  including Tasks without delivered files, under one eight-second index deadline.
  The replacement reads owned, server-produced assistant file references in
  bounded keyset pages and fetches only those exact assets. References survive
  Task replacement and retained conversation deletion. A refresh clears partial
  state; explicit pagination appends and deduplicates assets.
- The Zebra all-artifact index verified object storage for every model/tool
  artifact. Index serialization now uses payload metadata; detail and content
  still verify payload availability/integrity through existing readers.
- Read transports incorrectly required agent.run, including the downloader's
  internal tool-run projection ID content route. GET/HEAD artifact transports now
  require artifact.read. Mutations and execution retain their existing scopes.
- Missing historical Host binding snapshots can use bounded canonical
  TASK_PREPARED ownership only for a canonical successful files.publish artifact.
  A fresh signed read grant must match Host, namespace, workspace, principal,
  origin and original thread. Existing conflicting bindings never use fallback.
- Trench grants remain internal. Exact persisted-file ownership is checked in
  the BFF before legacy fallback. Grants carry artifact.read only; each namespace
  or historical thread-format attempt uses a fresh single-use grant. Only 404
  permits fallback; 403 stops. No execution binding is invented or persisted.
- Existing media.import_historical deliveries may appear in the owned index.
  Their original sensitive/full_access policy remains; they are not relabelled
  as canonical files.publish or granted workspace_write access.

## Local runtime restoration

Both API services retain their prior environment, mounts, security settings and
namespace. The historical API image could not restart against the current shared
schema. It now uses the compatible current API base with the same recovery
patches. The current API keeps its pool-enabled entrypoint; the legacy service
also uses that compatible entrypoint. Worker and Search were not replaced.

The TLS gateway adds exact-file metadata GET/HEAD to its existing historical
preview/download allowlist. Task lists, commands and arbitrary routes remain
unavailable through the historical prefix.

Six retained Tasks needed explicit metadata preparation after previous schema
upgrades. Existing bounded observation-header, Event-position, projection-source
and replay-header maintenance helpers were used only for those Tasks. Canonical
Event IDs, session IDs, sequence, type and payload hashes were identical before
and after. No schema migration, business-data rewrite, synthesized binding or
coverage privacy bypass was performed. All six canonical stream sources now
qualify and remain non-strict; strict coverage refusal regressions still pass.

Rollback bases and private configuration/evidence are under
.artifacts/trn-asset-recovery-01/. The original legacy image remains saved, but
cannot start against the current schema; use the compatible current base for
operational rollback. No production deployment is included.

## Validation

- Red-first index object-I/O, historical references, scope selection and internal
  content-alias regressions; cross-user/workspace, user-role forged references,
  expiry, thread/namespace drift, failed/internal/denied artifacts and 403 fallback
  refusal covered. Pagination retains 52 exact files across two pages.
- Focused Zebra artifact/scope/ownership tests: 42 passed, 20 environment skips.
  Strict coverage and identity repair tests: 30 passed.
- Scoped AG-UI read regression: 39 passed. Two full-suite failures came from an
  80 ms test scheduling window expiring before the first scoped read. The test
  now observes the read before disconnecting; dedicated authorization-expiry
  tests remain unchanged.
- Trench complete make check passed; final backend rerun: 243 passed, 62 native
  environment skips; cleaning 80 passed; frontend 505 passed, lint/builds and
  offline migration SQL passed. New focused historical asset suite: 31 passed.
- Unauthenticated real asset list returned 401. The real browser lists all 17
  objects without a partial-index warning; all 14 file downloads return 200.
- Final Zebra make check passes: 3,162 files within size limits, Ruff clean,
  mypy 1,296 files clean, deterministic eval 30/30 and both repair/risk gates pass.
- Full make test completed: 9,718 passed, 2,923 environment skips, one failed
  issuer-isolation fixture which still requested only agent.run/event.read.
  The fixture now requests artifact.read so the test reaches issuer validation.
  Post-fix issuer/thread suite: 16 passed; pytest --last-failed: 1 passed.
  There were no production-code changes during or after this full run. The full
  suite was not repeated after this final test-fixture-only correction; the
  complete run and subsequent focused reruns are recorded separately.

Runnable verification from this repository:

```sh
uv run pytest -q tests/api/test_legacy_artifact_authority.py tests/api/test_artifact_read_scopes.py tests/api/test_task_principal_guard.py tests/api/session_artifacts
make check
make test
```

User-authorized delivery targets: Zebra cloud-agent-trench and Trench main. No new
branch. Unrelated dirty files remain outside this changeset.
