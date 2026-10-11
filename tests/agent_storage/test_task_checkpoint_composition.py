"""The production Task facades must expose implementations, not Protocol stubs."""

import pytest
from agent_core.ports.task_projection_checkpoints import ProjectionCheckpointHead
from agent_storage.agent_tasks import SQLiteAgentTaskStore
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.migration_catalog_tail import LATEST_MIGRATIONS
from agent_storage.postgres.projection_source_metadata_migration import (
    TASK_PROJECTION_SOURCE_METADATA_MIGRATION,
)
from agent_storage.postgres.task_event_source_bounds_migration import (
    TASK_EVENT_SOURCE_BOUNDS_MIGRATION,
)
from agent_storage.postgres.task_projection_checkpoints import PostgresTaskProjectionCheckpointMixin
from agent_storage.postgres.task_projection_checkpoints_migration import (
    TASK_PROJECTION_CHECKPOINTS_MIGRATION,
)
from agent_storage.postgres.task_replay_scalar_header_migration import (
    TASK_REPLAY_SCALAR_HEADER_MIGRATION,
)
from agent_storage.task_projection_checkpoints import SQLiteTaskProjectionCheckpointMixin

from tests.agent_storage import test_postgres_task_projection_checkpoints as quality
from tests.agent_storage.test_task_projection_checkpoints import _fixture

checkpoint_dsn = quality.checkpoint_dsn
METHODS = (
    "read_checkpoint_head",
    "read_event_projection_header",
    "read_segment_checkpoint_before",
    "read_cells_at",
    "commit_projection_page",
)


@pytest.mark.parametrize(
    "facade,implementation",
    [
        (SQLiteAgentTaskStore, SQLiteTaskProjectionCheckpointMixin),
        (PostgresAgentTaskStore, PostgresTaskProjectionCheckpointMixin),
    ],
)
def test_task_facade_resolves_real_checkpoint_methods(facade: type, implementation: type) -> None:
    for name in METHODS:
        assert getattr(facade, name) is getattr(implementation, name)


def test_checkpoint_schema_is_in_the_production_migration_catalog() -> None:
    assert TASK_PROJECTION_CHECKPOINTS_MIGRATION in LATEST_MIGRATIONS
    assert TASK_EVENT_SOURCE_BOUNDS_MIGRATION in LATEST_MIGRATIONS
    assert TASK_REPLAY_SCALAR_HEADER_MIGRATION in LATEST_MIGRATIONS
    assert TASK_PROJECTION_SOURCE_METADATA_MIGRATION in LATEST_MIGRATIONS
    versions = [migration.version for migration in LATEST_MIGRATIONS]
    assert versions == sorted(set(versions))


def test_sqlite_task_facade_installs_scalar_header_columns_before_indexes(tmp_path) -> None:
    store = SQLiteAgentTaskStore(tmp_path / "fresh.sqlite")
    with store._database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(session_events)")}
    assert {"replay_command_kind", "replay_run_id", "replay_header_ready"} <= columns


def test_sqlite_legacy_headers_require_explicit_bounded_adoption(tmp_path) -> None:
    store, scope, _ = _fixture(tmp_path / "legacy.sqlite")
    with pytest.raises(ValueError, match="explicit backfill"):
        store.read_run_header(scope.task_id, "legacy")
    assert store.backfill_replay_headers(scope.task_id, limit=1) is False
    restored = SQLiteAgentTaskStore(store._database.database_path)
    assert restored.backfill_replay_headers(scope.task_id, limit=2) is True
    assert restored.read_run_header(scope.task_id, "legacy").legacy is True


def test_real_postgres_task_facade_reads_checkpoint_head(checkpoint_dsn: str) -> None:
    scope, _ = quality._seed(checkpoint_dsn, 1)
    store = PostgresAgentTaskStore(checkpoint_dsn, deployment_namespace=quality.NS)
    assert store.read_checkpoint_head(scope) == ProjectionCheckpointHead(scope)
