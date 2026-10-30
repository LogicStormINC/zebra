"""Composition retains both branches with immutable migration bodies."""

from agent_storage.postgres.migrations import MIGRATIONS


def test_combined_migration_catalog_is_ordered_and_unique():
    assert [m.version for m in MIGRATIONS] == [*range(1, 71), *range(72, 120)]
    assert len({m.name for m in MIGRATIONS}) == len(MIGRATIONS)
    assert [m.name for m in MIGRATIONS[-5:]] == [
        "agui_profile_projection_routing",
        "standard_projection_cells",
        "agent_safety_overrides",
        "runtime_admission_gate",
        "runtime_gate_original_termination",
    ]
