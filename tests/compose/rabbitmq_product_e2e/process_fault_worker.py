"""Real migrated process loop, injected transport/executor, isolated test schema only.

This is NOT evidence of a Rabbit ACK or OCI operation. No production hooks are added.
"""

import asyncio
import json
import os
import re
from dataclasses import replace
from threading import Event
from time import monotonic, sleep

import psycopg
from agent_core.domain.events import EventType
from agent_storage.postgres.command_wakeup import _canonical_json
from psycopg.conninfo import conninfo_to_dict
from zebra_agent_config import load_settings
from zebra_agent_config.command_delivery import CommandDeliverySettings
from zebra_agent_worker import command_process
from zebra_agent_worker.command_process_state import command_cutover_state

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup_receipts import _commit, _event


def validate_target(dsn: str, *, child: bool = False) -> str | None:
    """Exact owned endpoint and explicit generated schema; errors never include inputs."""
    try:
        target = conninfo_to_dict(dsn)
        allowed = {"host", "port", "dbname", "user", "password"} | ({"options"} if child else set())
        if (
            target.keys() - allowed
            or target.get("host") != "127.0.0.1"
            or target.get("port") != "28432"
            or target.get("user") != "e2e"
            or target.get("dbname") != "zebra_stage3_e2e"
            or not re.fullmatch(r"[0-9a-f]{48}", target.get("password", ""))
        ):
            raise ValueError
        if child:
            match = re.fullmatch(
                r"-c search_path=(process_fault_[0-9a-f]{32})", target.get("options", "")
            )
            if match is None:
                raise ValueError
            return match[1]
    except Exception:
        raise ValueError("process fault target is not the explicit isolated fixture") from None
    return None


def emit(code: str) -> None:
    print(json.dumps({"checkpoint": code}), flush=True)


def run(dsn: str, mode: str) -> None:
    schema = validate_target(dsn, child=True)
    if mode not in {"crash_before_ack", "broker", "fallback", "occupied", "poison"}:
        raise ValueError("unsupported fault mode")
    with psycopg.connect(dsn) as connection:
        if connection.execute("SELECT current_schema()").fetchone() != (schema,):
            raise ValueError("test schema unavailable")
    assert command_cutover_state(dsn, NAMESPACE, require_ready=True)
    gate = Event()
    if mode in {"fallback", "occupied", "poison"}:
        gate.set()

    def execute(lease, **_kwargs):
        if not gate.wait(10):
            raise RuntimeError("execution barrier timed out")
        started = _event(
            dsn, lease.session_id, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}
        )
        _commit(dsn, started, lease)
        emit("started")
        if mode == "occupied":
            deadline = monotonic() + 10
            while monotonic() < deadline:
                with psycopg.connect(dsn) as connection:
                    released = connection.execute(
                        "SELECT released_at IS NOT NULL FROM worker_leases WHERE session_id=%s",
                        (lease.session_id,),
                    ).fetchone()
                if released == (True,):
                    emit("revoked_while_occupied")
                    return
                sleep(0.02)
            raise RuntimeError("control barrier timed out")
        # A deterministic effect witness, deliberately not unique: duplicates remain observable.
        from agent_storage.postgres.database import PostgresDatabase
        from agent_storage.postgres.leases import assert_current_lease_fence

        with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as connection:
            assert_current_lease_fence(connection, NAMESPACE, lease.session_id, lease.fence)
            connection.execute(
                "INSERT INTO process_effects(session_id) VALUES (%s)", (lease.session_id,)
            )
        _commit(dsn, _event(dsn, lease.session_id, EventType.SESSION_COMPLETED), lease)
        emit("handled")

    class Delivery:
        def __init__(self, body):
            self.body = body

        async def ack(self):
            if mode == "crash_before_ack":
                emit("handoff_committed_before_ack")
                os._exit(73)  # Intentional process death, before execution or transport ACK.
            gate.set()
            emit("ack")

        async def requeue(self):
            emit("requeued")

    class Transport:
        def __init__(self, *_args, **_kwargs):
            self.pump = None
            self.stopped = False

        async def start(self):
            pass

        async def publish(self, _body, **_routing):
            pass  # Injected confirmation, explicitly not a broker proof.

        async def publish_diagnostic(self, _body, **_routing):
            emit("diagnostic_confirmed")

        async def consume(self, _queue, handler):
            async def pump():
                seen = set()
                while not self.stopped:

                    def bodies():
                        with psycopg.connect(dsn) as connection:
                            return connection.execute(
                                "SELECT message_id,envelope_json FROM broker_outbox "
                                "WHERE status='published' ORDER BY created_at,message_id"
                            ).fetchall()

                    for identity, envelope in await asyncio.to_thread(bodies):
                        if self.stopped:
                            break
                        if identity not in seen:
                            seen.add(identity)
                            await handler(Delivery(_canonical_json(envelope).encode()))
                    await asyncio.sleep(0.02)

            self.pump = asyncio.create_task(pump())
            return "injected-tag"

        async def stop_consuming(self, *_args):
            self.stopped = True
            if self.pump is not None:
                await self.pump

        async def close(self):
            self.stopped = True

    broker = mode in {"crash_before_ack", "broker", "poison"}
    settings = replace(
        load_settings(env={}),
        command_delivery=CommandDeliverySettings(
            publish_enabled=broker,
            consume_enabled=broker,
            scan_fallback_enabled=mode not in {"crash_before_ack", "broker"},
            relay_url="amqp://fake:fake@localhost:5672/test" if broker else None,
            consumer_url="amqp://fake:fake@localhost:5672/test" if broker else None,
            execution_slots=1,
            batch_size=1,
            tick_seconds=0.05,
        ),
    )
    # No engine probe or destruction in this process matrix; real cleanup has its own suite.
    command_process.pin_cloud_engine = lambda _settings: None
    command_process.cleanup_runtime_batch = lambda *_args, **_kwargs: None
    emit("ready")
    command_process.CommandWorkerProcess(
        dsn=dsn,
        namespace=NAMESPACE,
        settings=settings,
        execute=execute,
        maintenance=lambda **_kwargs: None,
        drain=lambda: emit("drained"),
        transport_factory=Transport,
    ).run(
        worker_id="process-fault-worker",
        batch_size=1,
        lease_ttl_seconds=5,
        max_cycles=6 if mode == "fallback" else 400,
        idle_sleep_seconds=0.05,
    )


if __name__ == "__main__":
    try:
        run(os.environ["ZEBRA_PROCESS_FAULT_DSN"], os.environ["ZEBRA_PROCESS_FAULT_MODE"])
    except BaseException:
        emit("process_failed")
        raise SystemExit(1) from None
