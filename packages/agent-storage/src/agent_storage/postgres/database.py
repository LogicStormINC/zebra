"""Small PostgreSQL connection boundary shared by the first cloud adapters."""

from contextlib import AbstractContextManager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from agent_storage.postgres.connection_pool import composition_pool
from agent_storage.postgres.task_io import TaskIoConnections, current_task_io_deadline


class PostgresDatabase:
    """Open short-lived connections for one immutable deployment namespace."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        task_io_connections: TaskIoConnections | None = None,
    ) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be blank")
        if not deployment_namespace or deployment_namespace != deployment_namespace.strip():
            raise ValueError("deployment namespace must be non-blank and trimmed")
        if len(deployment_namespace) > 255:
            raise ValueError("deployment namespace must not exceed 255 characters")
        self._dsn = dsn
        self._deployment_namespace = deployment_namespace
        self._pool = composition_pool(dsn)
        if task_io_connections is not None:
            task_io_connections.require_compatible(dsn)
        self._task_io = task_io_connections

    @property
    def deployment_namespace(self) -> str:
        return self._deployment_namespace

    def connect(self) -> AbstractContextManager[psycopg.Connection[dict[str, Any]]]:
        if (deadline := current_task_io_deadline()) is not None:
            return self.connect_task_io(deadline=deadline)
        if self._pool is not None:
            return self._pool.connection()
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def connect_task_io(
        self,
        *,
        timeout_seconds: float = 2,
        deadline: float | None = None,
        client_cursor: bool = False,
    ) -> psycopg.Connection[dict[str, Any]]:
        if self._task_io is None:
            self._task_io = TaskIoConnections(self._dsn)
        return self._task_io.connect(
            timeout_seconds=timeout_seconds,
            deadline=deadline,
            client_cursor=client_cursor,
        )
