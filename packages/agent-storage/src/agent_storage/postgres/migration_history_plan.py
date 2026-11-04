"""Exact branch-history compatibility without rewriting migration ledger rows."""

from collections.abc import Mapping
from dataclasses import replace

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.projection_work_repair_plan_migration import (
    PROJECTION_WORK_REPAIR_PLAN_MIGRATION,
)
from agent_storage.postgres.runtime_gate_migration import RUNTIME_GATE_MIGRATION


def migration_history_plan(
    applied: Mapping[int, tuple[str, str]],
    catalog: tuple[Migration, ...] = MIGRATIONS,
) -> tuple[Migration, ...]:
    """Keep published P5 115/116 identities; use the free slots for AG-UI.

    Every row still undergoes full version/name/checksum verification by the
    caller. An unrecognised checksum never selects this compatibility plan.
    No applied row, migration body, business record or receipt is rewritten.
    """
    if applied.get(115) != (RUNTIME_GATE_MIGRATION.name, RUNTIME_GATE_MIGRATION.checksum):
        return catalog
    slots = {115: 118, 116: 119, 118: 115, 119: 116}
    return tuple(replace(m, version=slots.get(m.version, m.version)) for m in catalog)

def runtime_schema_matches(
    applied: Mapping[int, tuple[str, str]],
    catalog: tuple[Migration, ...] = MIGRATIONS,
) -> bool:
    """Allow only the exact before/after ledgers for the additive repair rollout."""
    plan = migration_history_plan(applied, catalog)
    if (
        plan and plan[-1] == PROJECTION_WORK_REPAIR_PLAN_MIGRATION
        and plan[-1].version not in applied
    ):
        plan = plan[:-1]
    return applied == {m.version: (m.name, m.checksum) for m in plan}
