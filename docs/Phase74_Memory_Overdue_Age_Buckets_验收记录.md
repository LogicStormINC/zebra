# Phase 74 Memory Overdue Age Buckets 验收记录

## Scope

Phase 74 focused on turning existing overdue flags into one deterministic
overdue-age bucketing layer.

The phase added one additive overdue-age read surface on top of the existing
pressure, aging, velocity, governance, overview, summary, queue, action-hint,
escalation, follow-up-window, and overdue-flag surfaces so operators can
quickly see how long each overdue scope has been outstanding.

## Completed Tasks

### P74-MEM-01 - Memory Overdue Age Buckets

Implemented behavior:

- Added one combined memory overdue-age read path anchored to a session and
  enriched by optional user and tenant scope ids.
- Reused the existing overdue helper instead of introducing another durable
  projection or scheduler.
- Exposed additive per-scope fields including `overdue_age_bucket`,
  `overdue_age_seconds`, `overdue_age_days`, and `overdue_age_reasons`.
- Added aggregate `overdue_age_bucket_counts` plus a cross-scope
  `highest_priority_overdue_age_*` rollup for fast operator inspection.
- Kept overdue-age classification deterministic with simple local buckets for
  `<1d`, `1-3d`, `3-7d`, and `>=7d`, plus explicit non-overdue handling.

Validation:

- `uv run pytest tests/api/test_memory_overdue_age_buckets.py tests/cli/test_cli_memory_overdue_age_buckets.py tests/test_memory_overdue_age_buckets_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_overdue_age_buckets.py tests/cli/test_cli_memory_overdue_age_buckets.py tests/test_memory_overdue_age_buckets_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue age buckets for repo, user,
  and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue age buckets stay explicitly scoped and local-first.

## Validation Notes

- Overdue-age buckets stayed as a pure read-time derivation over the current
  overdue helper, which kept the implementation local-first and deterministic.
- The highest-priority rollup favors the most severe overdue bucket instead of
  reintroducing a new scoring model.

## Known Deferrals

- Overdue-age buckets are intentionally coarse; there is no business-calendar
  adjustment, grace period policy, or multi-breach trend analysis yet.
- The phase classifies overdue duration, but it does not yet summarize overdue
  counts by memory type or visibility class.

## Next Phase

Phase 75 should focus on deterministic overdue memory-type rollups:

- add one additive overdue-type layer on top of current overdue-age evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
