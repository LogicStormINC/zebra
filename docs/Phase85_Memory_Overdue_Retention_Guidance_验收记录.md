# Phase 85 Memory Overdue Retention Guidance 验收记录

## Scope

Phase 85 focused on improving overdue aftercare handling by mapping current
overdue archive recommendations to deterministic retention guidance.

The phase added one additive overdue-retention-guidance read surface on top of
the existing overdue archive-recommendation evidence so operators can see how a
scope should be retained while it remains overdue and not yet archived.

## Completed Tasks

### P85-MEM-01 - Memory Overdue Retention Guidance

Implemented behavior:

- Added one combined memory overdue-retention-guidance read path anchored to a
  session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-archive-recommendation helper instead of adding a
  new projection or background workflow.
- Exposed additive per-scope fields including
  `overdue_retention_guidance`, `overdue_retention_priority`,
  `overdue_retention_bucket`, `overdue_retention_target_memory_id`, and
  `overdue_retention_reasons`.
- Added aggregate `overdue_retention_guidance_counts` plus a cross-scope
  `highest_priority_overdue_retention_*` rollup for fast operator inspection.
- Kept retention guidance selection deterministic by mapping current overdue
  archive recommendations to stable guidance such as
  `retain_until_next_review`,
  `retain_until_same_day_follow_through`,
  `extend_retention_until_operator_completion`, and
  `extend_retention_until_owner_confirmation`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_retention_guidance.py tests/cli/test_cli_memory_overdue_retention_guidance.py tests/test_memory_overdue_retention_guidance_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_guidance.py tests/cli/test_cli_memory_overdue_retention_guidance.py tests/test_memory_overdue_retention_guidance_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue retention guidance for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue retention guidance stays explicitly scoped and local-first.

## Validation Notes

- The retention guidance is intentionally derived from current overdue
  archive-recommendation evidence, not from external timers or archival jobs,
  so the feature stays local-first and deterministic.
- The additive `overdue_retention_bucket` field gives operators a stable
  posture summary without introducing TTL promises or background services.

## Known Deferrals

- Overdue retention guidance still does not emit an explicit archival TTL.
- The phase does not yet model post-archive reopen guidance.

## Next Phase

Phase 86 should focus on deterministic overdue retention windows:

- add one additive timing-window layer on top of current overdue retention guidance
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
