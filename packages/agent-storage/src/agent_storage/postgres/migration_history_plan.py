"""Exact branch-history compatibility without rewriting migration ledger rows."""

from collections.abc import Mapping
from dataclasses import replace

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.orchestration_gate_migration import ORCHESTRATION_GATE_MIGRATION
from agent_storage.postgres.runtime_gate_migration import RUNTIME_GATE_MIGRATION


def migration_history_plan(
    applied: Mapping[int, tuple[str, str]],
    catalog: tuple[Migration, ...] = MIGRATIONS,
) -> tuple[Migration, ...]:
    """Select exact published branch histories without rewriting applied rows.

    Callers still verify every version, name and checksum. Unrecognised
    checksums never select a compatibility mapping.
    """
    slots: dict[int, int] = {}
    if applied.get(115) == (RUNTIME_GATE_MIGRATION.name, RUNTIME_GATE_MIGRATION.checksum):
        slots.update({115: 118, 116: 119, 118: 115, 119: 116})
    if applied.get(122) == (
        ORCHESTRATION_GATE_MIGRATION.name,
        ORCHESTRATION_GATE_MIGRATION.checksum,
    ):
        # The candidate published observations at 122 and policy at 123.
        # Its missing Host manifest migration uses the free slot 124.
        slots.update({122: 124, 123: 122, 124: 123})
    if not slots:
        return catalog
    return tuple(replace(m, version=slots.get(m.version, m.version)) for m in catalog)
