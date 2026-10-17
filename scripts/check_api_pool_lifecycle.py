"""Check API pool ownership with ZEBRA_TEST_POSTGRES_DSN, without serving or models."""

import os
from types import SimpleNamespace
from unittest.mock import patch

from agent_storage.postgres.connection_pool import composition_pool
from agent_storage.postgres.database import PostgresDatabase
from psycopg.pq import TransactionStatus
from zebra_agent_api import server


def check() -> None:
    dsn = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    settings = SimpleNamespace(storage_authority="postgresql", database_url=dsn)
    seen = []

    def run_cli(*, args):
        pool = composition_pool(dsn)
        assert pool is not None
        seen.append(pool)
        pool.resize(1, 1)
        pool.wait()
        assert args[:6] == [
            "zebra_agent_api.http:create_http_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ]
        assert args[6:] == ["--log-level", "warning"]
        pids = []
        for _ in range(2):
            # New adapters, separate transactions, same bounded process pool.
            store = PostgresDatabase(dsn, deployment_namespace="api-pool-check")
            with store.connect() as connection:
                pids.append(connection.info.backend_pid)
                assert connection.execute("SELECT 1 AS value").fetchone()["value"] == 1
            assert connection.info.transaction_status is TransactionStatus.IDLE
        assert pids[0] == pids[1]
        raise RuntimeError("startup-or-server-failure")

    with (
        patch.object(server, "load_settings", return_value=settings),
        patch.object(
            server,
            "uvicorn_main",
            side_effect=run_cli,
        ),
    ):
        try:
            server.main(["--log-level", "warning"])
        except RuntimeError as exc:
            assert str(exc) == "startup-or-server-failure"
        else:
            raise AssertionError("server failure must propagate")
    assert len(seen) == 1 and seen[0].closed
    assert composition_pool(dsn) is None
    with (
        patch.object(
            server,
            "load_settings",
            return_value=SimpleNamespace(
                storage_authority="sqlite",
                database_url="local.sqlite",
            ),
        ),
        patch.object(server, "postgres_pool_scope", side_effect=AssertionError("local used pool")),
        patch.object(
            server,
            "uvicorn_main",
            return_value=None,
        ) as cli,
    ):
        server.main([])
        cli.assert_called_once()
    print("API reuses bounded pool, closes it on failure, keeps argv and local SQLite path")


if __name__ == "__main__":
    check()
