"""Composition retains both branches with immutable migration bodies."""

from agent_storage.postgres.migrations import MIGRATIONS


def test_combined_migration_catalog_is_ordered_and_unique():
    assert [m.version for m in MIGRATIONS] == [*range(1, 71), *range(72, 128)]
    assert len({m.name for m in MIGRATIONS}) == len(MIGRATIONS)
    assert [m.name for m in MIGRATIONS[-6:]] == [
        "projection_work_shared_admission_lock",
        "projection_work_repair_plan_reuse",
        "command_outbox_terminal_fallback_retirement",
        "command_outbox_unpublished_capacity_index",
        "force_stop_executor_receipt_prefix_index",
        "coverage_model_source_compare",
    ]
