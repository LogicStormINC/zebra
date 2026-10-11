# Local branch integration — 2026-10-12

## Authority and recovery boundary

User approved regression repair before local consolidation. Zebra integrates
into `cloud-agent-trench`; `cloud-agent` and `main` remain. Trench integrates
into `main`, retaining only that local branch. This is not authorization for
GitHub publication, remote branch deletion, service restart, business migration
or activation of coverage execution receipts.

Private recovery bundle and per-worktree binary patches/archives:
`/Users/lukeding/Desktop/playground/2026/product/branch-integration-backup-20261011-vzRHb3`.
All nine Zebra and two Trench stashes remain unchanged. Ignored runtime data,
volumes, credentials and independently edited primary SDK files are not staged.
Old checkouts are retained detached rather than deleting their files.

## Reconciliation and regression repairs

- Preserve bounded progressive delivery, task/lease authority and coverage
  proof contracts together; no rollback to the older unbounded recovery API.
- Update stale transaction/cache-owner/paging test doubles instead of deleting
  tests or relaxing missing-source, tamper, fencing or publication checks.
- Retain connection ownership, deadline propagation and native bounded object
  reads; standalone task reads use the existing bounded I/O path.
- Separate recoverable Worker errors from fixed strict-coverage refusals and
  finalize a resumed coverage run with its durable progressive attempt number.
- Preserve assistant-role validation; add safe typed validation diagnostics
  without copying provider text into errors.
- Strict coverage uses its own versioned AG-UI checkpoint and bounded keyed
  progress cells. Source-owned indexed presence determines Task-wide privacy,
  including late/malformed admissions; cold resume never releases private model
  or tool text from an earlier prefix.
- Native authority pinning uses the same Task61 lock as binding renewal. The
  final fresh locked recheck follows session/lease/event mutations, preventing
  shared-to-exclusive upgrade deadlocks and rolling back changed authority.
- MODEL witnesses compare immutable source fields, not late Task coordinates.
  Native coordinate guards remain mandatory. Metadata-only allocation neither
  invalidates the MODEL summary nor changes its revision; native whole-row byte
  accounting is adjusted exactly. Business-source or witness tampering still
  fails closed; invalidated legacy summaries are never requalified.
- Projection work is routed to exactly one source-owned checkpoint version.
  Ordinary/coverage source hooks no longer broadcast both versions. Wrong-version
  work is parked without a retry loop or false acknowledgement; late strict
  admission requeues prior closed anchors under the correct privacy version.
  Native Task joins remain namespace constrained, including colliding Task IDs.

## Additive migrations

Each original checkout registers 77 migrations; the union contains 93 historical
identities. All 93 identities/checksums match their original checkout(s). Catalog
composition is ordered without renumbering historical DDL.

| Version | Purpose |
| --- | --- |
| 95 | Extend derived checkpoint cells for coverage progress |
| 96 | Separate late Task coordinates from MODEL source mutation |
| 97 | Indexed source-owned strict-coverage privacy presence |
| 98 | Source-owned checkpoint work routing and late-privacy repair |

SQLite upgrades only derived cells/indexes, retaining existing cells, indexes
and triggers; canonical Event bodies are not rewritten by this upgrade.
Trench adds the no-op Alembic merge head `c2d3e4f5a6b7` above coverage snapshot
and binding migrations, preserving both independent histories.
No application database has been upgraded by this task.

## Validation ledger

Coverage checkpoint repair: six focused modules 111 passed; its full pre-merge
suite 6998 passed / 2033 environment-dependent skips.

Combined Zebra validation passed after the repairs below. Completed focused checks:

The first combined pass reported 29 failures / 8922 passes / 2481 skips. After
initial repairs, the next pass reported 26 failures / 8969 passes / 2492 skips
in 900.59 seconds, all in checkpoint privacy/metadata-read compatibility and
header-cost gates. This run collected source before the final metadata/routing
repairs; it is retained as failed evidence, not a final green gate.

An intermediate five-module checkpoint regression rerun: 130 passed / 10 backend skips /
4 failures in 181.58 seconds. The original API/consumer failures no longer
reproduce; remaining failures are the unchanged scalar VM-cost gate and a missing
metadata index on the legacy installer path. Independent routing review found
wrong-version queues remaining hot and source hooks broadcasting both versions;
bounded source-owned routing/late strict-flip closure was subsequently repaired.

Final scalar-header lane: 31 passed / one backend skip; separate isolated native
header suite 14 passed. Cold 1k/10k/100k probes use 780 VM steps (unchanged `<800`
limit), maximum one row visit, zero decoded bodies; measured cold header reads
approximately 1.3–1.6 ms. This is not conversation latency or p95 evidence.
Latest main routing/scalar rerun: 34 passed / 19 environment skips. Explicit
PostgreSQL routing/privacy rerun: 47 passed / 14 skips (separate header scratch
configuration plus backend-specific cases); additive migration checks six passed.
Final staged `make check` passed: 2920 file-size checks, Ruff, Mypy 1231 files,
deterministic eval 30/30. Final native routing rerun: 36 passed / six backend
skips in 48.91 seconds; native source-position checks: seven passed. Source-owned
routing lane checks: 33 passed / two backend skips, including 17 native checks.
Final combined full-source `make test`: **9011 passed / 2511 environment-dependent
skips / zero failures**, 1054.58 seconds. `make check` rerun also passed after
the final composition-test correction. Native checks were run separately in
disposable schemas; skipped prerequisites are not claimed as covered by this run.

The next combined full pass reported 9010 passed / 2511 skipped / one failure
in 1081.17 seconds. The sole failure was the composition test's stale exhaustive
field list, missing the added coverage queue. Updated the list and checked that
the coverage queue is independently composed and empty before activation;
composition/routing rerun: 18 passed / 19 backend skips. This failed full run
remains in the ledger; the subsequent full passing run is the merge gate.

- 89 compatibility/Worker/provider regression tests;
- 31 cancellation, recovery-read and receipt-budget tests;
- 57 progressive/checkpoint/stream projection tests;
- 65 native storage/migration/transaction tests in disposable PostgreSQL schemas;
- 80 native admission/renewal/duplicate-handoff authority tests;
- 13 native/SQLite privacy checkpoint tests, one backend-specific expected skip;
- 17 native Worker dispatch tests, using explicit signed Host/model/object
  transport fixtures rather than claiming live service acceptance.

Trench `make check` passed: API 233 passed / 62 infrastructure skips; cleaning
80 passed; ToC 466 passed. Frontend builds, ESLint and migration SQL/head checks
passed. An additional 70 native coverage/history checks passed in disposable
schemas; no production migration was applied.

## Remaining acceptance, not hidden by a merge

- The existing nine-record strict workload records **10497 client SQL calls**;
  the `<=1000` SQL gate remains **FAIL**. This integration is not a root-cure,
  throughput, latency or p95 acceptance claim. This workload was not rerun here.
- Coverage execution receipts remain disabled; fleet fairness/load, immutable
  object retention, joint live runtime acceptance and business semantic accuracy
  are separate uncompleted release gates.
- Remote publication/deletion and runtime deployment remain user-controlled.
- New independently edited primary SDK files and historical unmatched stashes
  are preserved, not silently committed or resurrected as current source.
