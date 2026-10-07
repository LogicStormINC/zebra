# Exhaustive Coverage Contracts Implementation Plan

> Use executing-plans for this isolated COV-CON-01 slice.

**Goal:** Establish fail-closed v1 scope, snapshot, unit and receipt contracts.

**Architecture:** Pure agent-core contracts and deterministic set validation.
Snapshot adapters and atomic Event/Artifact commits stay behind Ports. This
slice cannot authorize publication or silently activate exhaustive admission.

**Tech Stack:** Python 3.12, existing Pydantic, hashlib/json, pytest.

## Chunk 1: Contracts and deterministic validation

- [x] Isolate committed baseline and run core baseline tests (881 passed).
- [x] Claim Ready COV-CON-01 in docs/AGENT_TASKS.md before implementation.
- [x] Add tests/agent_core/test_coverage_contracts.py and prove import failure.
- [x] Add domain/coverage_contracts.py for bounded scope, check versions and hashes.
- [x] Add domain/coverage_snapshot.py for frozen record/part identities and pages.
- [x] Add domain/coverage_validation.py for receipt shape and exact-set verdicts.
- [x] Add ports/coverage.py for snapshot reads and fenced Event/Artifact commits.
- [x] Run uv run pytest -q tests/agent_core/test_coverage_contracts.py (pass).
- [x] Run uv run pytest -q tests/agent_core (baseline + new regressions pass).
- [x] Run make check and report full-gate evidence separately.
- [x] Document bindings, ceilings and unsupported capabilities in
  docs/COVERAGE_CONTRACTS.md; update PROGRESS.md, registry and WORKLOG.md.

Evidence: focused 50 passed; core 931 passed; full 4,925 passed, 911 environment
skips; make check passed. This does not establish real snapshot or cloud E2E.

Required regression: expected units A/B, accepted A/C must fail despite equal
counts. A 10,003-record set must validate without treating pagination count as
identity proof. Empty authorized sealed sets have no percentage denominator.

## Deferred dependent slices

TRN-COV-SNAPSHOT-01, COV-STO-01, COV-EXEC-01, COV-GATE-01, COV-UI-01,
COV-ACCEPT-01 follow the source design's merge dependency order. No application
restart, migration, merge, push or deployment is part of this contract task.
