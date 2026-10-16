"""Existing remaining-budget SQL adapter for PostgreSQL projection maintenance."""

import time
from collections.abc import Mapping, Sequence
from typing import Any

from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from psycopg import Connection, Cursor
from psycopg.errors import QueryCanceled


class _WorkConnection:
    """Remaining SQL operation budget, shared by all statements and COMMIT."""

    def __init__(self, connection: Connection[dict[str, Any]], deadline: float) -> None:
        self.connection, self.deadline = connection, deadline

    def execute(
        self, statement: str, params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> Cursor[dict[str, Any]]:
        remaining = int((self.deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            raise CheckpointNotReady("projection-work operation I/O deadline exceeded")
        try:
            self.connection.execute(
                "SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                (f"{remaining}ms", f"{min(50, remaining)}ms"),
            )
            return self.connection.execute(statement, params)
        except (QueryCanceled, TimeoutError) as exc:
            raise CheckpointNotReady("projection-work operation I/O deadline exceeded") from exc

    def commit(self) -> None:
        self.execute("COMMIT")
