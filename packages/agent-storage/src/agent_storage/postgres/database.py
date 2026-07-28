"""Small PostgreSQL connection boundary shared by the first cloud adapters."""

from typing import Any

import psycopg
from psycopg.rows import dict_row


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
        return psycopg.connect(self._dsn, row_factory=dict_row)
