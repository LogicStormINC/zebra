"""Real PostgreSQL adapter/consumer scan baseline; synthetic data, no model execution.

RABBITMQ_BASELINE_DSN must name the disposable localhost rabbitmq_baseline DB.
Applies actual Zebra migrations there. Never point this script at a service DB.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import gettempdir
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage.postgres.events import PostgresEventStore, append_event_in_transaction
from agent_storage.postgres.migration_runner import apply_postgres_migrations
from agent_storage.postgres.projections import (
    PostgresProjectionStore,
    save_session_in_transaction,
)
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from zebra_agent_worker.command_consumer import SessionCommandConsumer


def benchmark(dsn: str, size: int, repeats: int) -> dict:
    namespace = f"benchmark-{uuid4().hex}"
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    sessions = PostgresProjectionStore(dsn, deployment_namespace=namespace)
    now = datetime.now(UTC)
    seeded = []
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        for index in range(size):
            bootstrap = SessionBootstrapService().build(
                SessionBootstrapCommand(
                    title="Synthetic scan baseline",
                    user_input="Do not execute a model",
                    workspace_root=Path(gettempdir()).resolve(),
                )
            )
            for event in bootstrap.events:
                append_event_in_transaction(connection, namespace, event)
            session = bootstrap.session.model_copy(
                update={"updated_at": now - timedelta(seconds=size - index)}
            )
            seeded.append(session)
            save_session_in_transaction(connection, namespace, session)
    oldest = seeded[0]
    command = SessionCommand(
        session_id=oldest.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=oldest.current_sequence,
        idempotency_key=f"baseline-{namespace}",
    )
    events.append(
        SessionEvent.create(
            session_id=oldest.session_id,
            sequence=oldest.current_sequence + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
            idempotency_key=command.idempotency_key,
        )
    )
    called = []

    class NoModelExecution:
        def execute_session(self, session_id, **_kwargs):
            called.append(session_id)

    # Only RUN is exercised; recovery workspace methods must never be called here.
    stores = SimpleNamespace(events=events, sessions=sessions, workspaces=None)
    consumer = SessionCommandConsumer(stores, NoModelExecution())
    queries = 0
    connections = 0

    class CountedConnection(psycopg.Connection):
        def execute(self, query, params=None, **kwargs):
            nonlocal queries
            queries += 1
            return super().execute(query, params, **kwargs)

    def counted_connect(*args, **kwargs):
        nonlocal connections
        connections += 1
        return CountedConnection.connect(*args, **kwargs)

    timings = []
    with patch("agent_storage.postgres.database.psycopg.connect", side_effect=counted_connect):
        for _ in range(repeats):
            start = time.perf_counter()
            result = consumer.consume_once(worker_id="baseline", lease_ttl_seconds=30, batch_size=1)
            timings.append((time.perf_counter() - start) * 1000)
            assert result.status == "idle", "old pending command unexpectedly found"
    assert not called
    scan_queries, scan_connections = queries, connections
    # Positive control: an expanded window finds the same command without touching its state.
    result = consumer.consume_once(worker_id="baseline", lease_ttl_seconds=30, batch_size=size)
    assert result.status == "executed" and called == [oldest.session_id]
    assert (
        events.list_for_session(oldest.session_id)[-1].event_type
        is EventType.SESSION_COMMAND_ACCEPTED
    )
    ordered = sorted(timings)
    return {
        "sessions": size,
        "repeats": repeats,
        "batch_size": 1,
        "namespace": namespace,
        "explicit_sql_queries": scan_queries,
        "connections": scan_connections,
        "queries_per_scan": scan_queries / repeats,
        "scan_latency_ms": {
            f"p{p}": round(ordered[math.ceil(repeats * p / 100) - 1], 3) for p in (50, 95, 99)
        },
        "old_pending_command_found": False,
        "positive_control_found": True,
    }


def checked_dsn(dsn: str) -> str:
    config = conninfo_to_dict(dsn)
    if (
        config.keys() - {"host", "port", "dbname", "user", "password"}
        or config.get("dbname") != "rabbitmq_baseline"
        or config.get("host") not in {"localhost", "127.0.0.1"}
        or not config.get("port", "").isdigit()
        or not 1 <= int(config["port"]) <= 65535
    ):
        raise ValueError(
            "Use an explicit local port and disposable rabbitmq_baseline DB; no options"
        )
    # Pin the address too: libpq otherwise honors inherited PGHOSTADDR over host.
    return make_conninfo(dsn, host="127.0.0.1", hostaddr="127.0.0.1", connect_timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="10,100,1000")
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes.split(",")]
    if (
        not sizes
        or any(not 9 <= value <= 10000 for value in sizes)
        or not 10 <= args.repeats <= 100
    ):
        parser.error("sizes must be 9..10000; repeats must be 10..100")
    dsn = checked_dsn(os.environ["RABBITMQ_BASELINE_DSN"])
    apply_postgres_migrations(dsn)
    with psycopg.connect(dsn) as connection:
        version = connection.execute("SHOW server_version").fetchone()[0]
    print(
        json.dumps(
            {
                "backend": f"PostgreSQL {version}",
                "mode": "real projection/event store+consumer; no model",
                "results": [benchmark(dsn, size, args.repeats) for size in sizes],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
