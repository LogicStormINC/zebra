"""Branch reconciliation preserves one owner and bounded Task I/O."""

from contextlib import nullcontext
from time import monotonic
from unittest.mock import Mock

import pytest
from agent_storage.postgres import database as boundary
from agent_storage.postgres.task_io import task_io_deadline
from agent_storage.postgres.work_unit import postgres_work_unit


@pytest.mark.parametrize("task_read", [False, True])
def test_work_unit_borrows_existing_pool_or_task_io_owner(monkeypatch, task_read):
    connection = Mock()
    pool = Mock()
    pool.connection.side_effect = lambda: nullcontext(connection)
    io = Mock()
    io.connect.side_effect = lambda **kwargs: nullcontext(connection)
    monkeypatch.setattr(boundary, "composition_pool", lambda dsn: pool)
    database = boundary.PostgresDatabase(
        "postgresql://localhost/fixture", deployment_namespace="tenant-a",
        task_io_connections=io,
    )
    deadline = monotonic() + 10
    scope = task_io_deadline(deadline) if task_read else nullcontext()
    with scope, postgres_work_unit(database), database.connect() as borrowed:
        borrowed.execute("SELECT 1")
        with database.connect() as nested:
            nested.execute("SELECT 2")
        connection.execute.assert_any_call("SELECT 1")
        connection.execute.assert_any_call("SELECT 2")
        connection.commit.assert_not_called()
        connection.close.assert_not_called()
    assert pool.connection.call_count == (not task_read)
    assert io.connect.call_count == task_read
    if task_read:
        assert io.connect.call_args.kwargs["deadline"] == deadline
    with pytest.raises(RuntimeError, match="ended"):
        borrowed.execute("SELECT 3")
