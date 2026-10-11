"""Small PostgreSQL connection boundary shared by the first cloud adapters."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

_deadline: ContextVar[float | None] = ContextVar("postgres_request_deadline", default=None)


@contextmanager
def postgres_deadline(deadline: float) -> Iterator[float]:
    """Explicit request scope, also covering nested adapters without mutating stores."""
    previous = _deadline.get()
    effective = min(previous, deadline) if previous is not None else deadline
    token = _deadline.set(effective)
    try:
        yield effective
    finally:
        _deadline.reset(token)


def current_postgres_deadline() -> float | None:
    return _deadline.get()


class PostgresDatabase:
    """Open short-lived connections for one immutable deployment namespace."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be blank")
        if not deployment_namespace or deployment_namespace != deployment_namespace.strip():
            raise ValueError("deployment namespace must be non-blank and trimmed")
        if len(deployment_namespace) > 255:
            raise ValueError("deployment namespace must not exceed 255 characters")
        self._dsn = dsn
        self._deployment_namespace = deployment_namespace

    @property
    def deployment_namespace(self) -> str:
        return self._deployment_namespace

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        from agent_storage.postgres.connection_scope import current_connection_scope
        from agent_storage.postgres.work_unit import borrow_work_unit

        deadline = current_postgres_deadline()
        unit = borrow_work_unit((self._dsn, self.deployment_namespace))
        if unit is not None:
            if deadline is not None:
                from agent_storage.postgres.coverage_recovery_preparation import (
                    RecoveryDeadlineConnection,
                )

                unit = RecoveryDeadlineConnection(unit, deadline)
            return cast(psycopg.Connection[dict[str, Any]], unit)

        scope = current_connection_scope()
        if scope is not None:
            from agent_storage.postgres.coverage_recovery_preparation import (
                CoverageRecoveryDeferred,
                RecoveryDeadlineConnection,
                remaining_recovery_time,
            )

            scoped_options: dict[str, Any] = {"row_factory": dict_row, "prepare_threshold": None}
            if deadline is not None:
                remaining = remaining_recovery_time(deadline)
                if remaining < 2:
                    raise CoverageRecoveryDeferred("insufficient database connection budget")
                scoped_options["connect_timeout"] = int(remaining)
            connection = scope.borrow(
                (self._dsn, self._deployment_namespace),
                lambda: psycopg.connect(self._dsn, **scoped_options),
            )
            if deadline is not None:
                connection = RecoveryDeadlineConnection(connection, deadline)
            return cast(psycopg.Connection[dict[str, Any]], connection)
        if deadline is None:
            return psycopg.connect(self._dsn, row_factory=dict_row)
        from agent_storage.postgres.coverage_recovery_preparation import (
            CoverageRecoveryDeferred,
            RecoveryDeadlineConnection,
            remaining_recovery_time,
        )

        remaining = remaining_recovery_time(deadline)
        # ponytail: libpq has a 2s minimum per-address timeout; DNS is not hard preemptible.
        if remaining < 2:
            raise CoverageRecoveryDeferred("insufficient database connection budget")
        options = psycopg.conninfo.conninfo_to_dict(self._dsn).get("options", "")
        milliseconds = max(1, int(remaining * 1000))
        connection = psycopg.connect(
            self._dsn, row_factory=dict_row, connect_timeout=int(remaining),
            options=f"{options} -c statement_timeout={milliseconds} -c lock_timeout={milliseconds}",
        )
        try:
            remaining_recovery_time(deadline)
        except CoverageRecoveryDeferred:
            connection.close()
            raise
        return cast(
            psycopg.Connection[dict[str, Any]], RecoveryDeadlineConnection(connection, deadline)
        )
