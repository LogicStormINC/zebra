# Phase 84 Memory Overdue Archive Recommendations 验收记录

## Scope

Phase 84 focused on improving overdue aftercare handling by mapping current
overdue scopes to deterministic archive recommendations.

The phase added one additive overdue-archive-recommendation read surface on top
of the existing pressure, aging, velocity, governance, overview, summary,
queue, action-hint, escalation, follow-up-window, overdue-flag, overdue-age,
overdue-type, overdue-visibility, overdue-trend, overdue-intervention,
overdue-escalation-lane, overdue-recovery-path, overdue-resolution-checkpoint,
overdue-resolution-outcome, and overdue-closure-decision surfaces so operators
can see whether a scope is ready for archive or should remain active.

## Completed Tasks

### P84-MEM-01 - Memory Overdue Archive Recommendations

Implemented behavior:

- Added one combined memory overdue-archive-recommendation read path anchored
  to a session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-closure-decision helper instead of introducing a
  new projection, scheduler, or workflow engine.
- Exposed additive per-scope fields including
  `overdue_archive_recommendation`, `overdue_archive_priority`,
  `overdue_archive_target_memory_id`, and `overdue_archive_reasons`.
- Added aggregate `overdue_archive_recommendation_counts` plus a cross-scope
  `highest_priority_overdue_archive_*` rollup for fast operator inspection.
- Kept recommendation selection deterministic by mapping current overdue
  closure decisions to stable archive recommendations such as
  `revisit_archive_after_next_review`,
  `revisit_archive_after_same_day_follow_through`,
  `retain_active_until_operator_completion`, and
  `retain_active_until_owner_confirmation`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_archive_recommendations.py tests/cli/test_cli_memory_overdue_archive_recommendations.py tests/test_memory_overdue_archive_recommendations_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_archive_recommendations.py tests/cli/test_cli_memory_overdue_archive_recommendations.py tests/test_memory_overdue_archive_recommendations_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue archive recommendations for
  repo, user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue archive recommendations stay explicitly scoped and local-first.

## Validation Notes

- The archive recommendation is intentionally derived from current overdue
  closure-decision evidence, not from external workflow state, so the feature
  stays local-first and deterministic.
- A scope can still remain on `revisit_archive_after_next_review` when the
  overdue breach is new; the phase reports the current archive posture instead
  of inferring archival readiness early.

## Known Deferrals

- Overdue archive recommendations do not yet emit an explicit retention bucket
  or archival TTL.
- The phase does not yet model post-archive recovery reopen guidance.

## Next Phase

Phase 85 should focus on deterministic overdue retention guidance:

- add one additive retention-guidance layer on top of current overdue archive-recommendation evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
