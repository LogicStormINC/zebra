"""Migration composition must retain immutable identities and dependency order."""

from agent_storage.postgres.migrations import MIGRATIONS


def test_combined_migration_catalog_is_ordered_and_unique():
    versions = [migration.version for migration in MIGRATIONS]
    assert versions == [*range(1, 71), *range(72, 109)]
    assert len({migration.name for migration in MIGRATIONS}) == len(MIGRATIONS)

    assert MIGRATIONS[-1].name == "host_registry_management"
