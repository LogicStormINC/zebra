"""Published branch ledger identities remain intact and checksum strict."""

from dataclasses import replace

from agent_storage.postgres.migration_history_plan import migration_history_plan
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.runtime_gate_migration import RUNTIME_GATE_MIGRATION
from agent_storage.postgres.runtime_gate_termination_migration import (
    RUNTIME_GATE_TERMINATION_MIGRATION,
)


def test_new_and_agui_histories_use_canonical_slots():
    assert migration_history_plan({}) == MIGRATIONS
    history = {m.version: (m.name, m.checksum) for m in MIGRATIONS if m.version <= 117}
    assert migration_history_plan(history) == MIGRATIONS


def test_original_p5_histories_keep_all_applied_rows():
    for tail in [
        (RUNTIME_GATE_MIGRATION,),
        (RUNTIME_GATE_MIGRATION, RUNTIME_GATE_TERMINATION_MIGRATION),
    ]:
        history = {m.version: (m.name, m.checksum) for m in tail}
        plan = migration_history_plan(history)
        assert len({m.version for m in plan}) == len(MIGRATIONS)
        assert {(m.name, m.checksum) for m in plan} == {(m.name, m.checksum) for m in MIGRATIONS}
        assert {m.version: (m.name, m.checksum) for m in plan if m.version in history} == history
        assert next(m for m in plan if m.version == 118).name == "agui_profile_projection_routing"
        assert next(m for m in plan if m.version == 119).name == "standard_projection_cells"


def test_unknown_checksum_does_not_enable_legacy_slot_mapping():
    migration = replace(RUNTIME_GATE_MIGRATION, statements=("SELECT 1",))
    assert migration_history_plan({115: (migration.name, migration.checksum)}) == MIGRATIONS


def test_historical_prefix_catalog_remains_supported():
    prefix = tuple(m for m in MIGRATIONS if m.version <= 109)
    assert migration_history_plan({}, prefix) == prefix
