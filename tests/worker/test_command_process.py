"""Process wiring uses real execution Futures, fake IO, and no external services."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from zebra_agent_config import load_settings
from zebra_agent_config.command_delivery import CommandDeliverySettings
from zebra_agent_worker import command_process as module


@pytest.fixture
def wired(monkeypatch):
    log = []
    objects = []
    lease = SimpleNamespace(session_id=uuid4())

    class Consumer:
        def __init__(self, dsn, **kwargs):
            self.options = kwargs
            self.pool = ThreadPoolExecutor(1)
            self.future = None
            objects.append(self)
            log.append(("dsn", dsn, kwargs["deployment_namespace"]))

        async def poll(self, lane, **_kwargs):
            log.append(lane)
            if lane == "execution" and self.future is None:
                self.future = self.pool.submit(self.options["execute_claimed"], lease)
                return (module.PickupOutcome.SCHEDULED,)
            return ()

        async def on_delivery(self, message):
            await self.options["quarantine"](b"bad", None, "invalid_broker_envelope")

        async def close(self):
            await asyncio.to_thread(self.pool.shutdown, wait=True)
            log.append("consumer-drained")

        def stop_new_admissions(self):
            log.append("admissions-stopped")

    class Quarantine:
        def __init__(self, dsn, **kwargs):
            self.publisher = kwargs["publish_confirmed"]

        async def __call__(self, *args):
            await self.publish_once()

        async def publish_once(self):
            await self.publisher(
                b"diagnostic",
                exchange="zebra.command.diagnostic.x",
                routing_key="delivery.rejected.v1",
            )

    class Transport:
        def __init__(self, url, **kwargs):
            self.url = url
            log.append("transport-created")

        async def start(self):
            log.append("transport-start")

        async def publish(self, body, **kwargs):
            assert body != b"diagnostic"
            log.append("command-publish")

        async def publish_diagnostic(self, body, **kwargs):
            assert body == b"diagnostic"
            log.append("diagnostic-publish")

        async def consume(self, queue, handler):
            log.append(("consume", queue))
            return "tag"

        async def stop_consuming(self, queue, tag):
            log.append("stop-consuming")

        async def close(self):
            log.append("transport-close")

    monkeypatch.setattr(module, "CommandWakeupConsumer", Consumer)
    monkeypatch.setattr(module, "CommandWakeupQuarantine", Quarantine)
    monkeypatch.setattr(
        module,
        "CommandRecoverySweep",
        lambda *args, **kwargs: SimpleNamespace(tick=lambda: log.append("recovery")),
    )
    monkeypatch.setattr(module, "pin_cloud_engine", lambda settings: object())
    monkeypatch.setattr(
        module, "cleanup_runtime_batch", lambda *args, **kwargs: log.append("cleanup")
    )
    return log, objects, lease, Transport


def _process(wired, config=None, execute=None, transport=None):
    log, objects, lease, factory = wired
    settings = replace(
        load_settings(env={}), command_delivery=config or CommandDeliverySettings(tick_seconds=0.05)
    )
    return module.CommandWorkerProcess(
        dsn="actual-composition-dsn",
        namespace="actual-namespace",
        settings=settings,
        execute=execute or (lambda supplied, **kw: log.append(("executed", supplied, kw))),
        maintenance=lambda **kw: log.append("child-and-memory"),
        drain=lambda: log.append("memory-drained"),
        transport_factory=transport or factory,
    )


def test_default_off_no_transport_and_exact_claimed_callback_ttl(wired):
    log, objects, lease, _ = wired
    result = _process(wired).run(worker_id="worker", lease_ttl_seconds=11, max_cycles=2)
    assert "transport-created" not in log
    assert objects[0].options["scoped_rollout"] is False
    assert ("executed", lease, {"lease_ttl_seconds": 11}) in log
    assert ("dsn", "actual-composition-dsn", "actual-namespace") in log
    assert result.executed_session_ids == (str(lease.session_id),)
    assert "child-and-memory" in log and "recovery" in log and "cleanup" in log
    assert log.index("consumer-drained") < log.index("memory-drained")


def test_full_execution_does_not_starve_control_and_drain_waits_real_future(wired):
    log, objects, lease, _ = wired
    started, finish = Event(), Event()

    def execute(*args, **kwargs):
        started.set()
        assert finish.wait(2)
        log.append("real-execution-finished")

    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(_process(wired, execute=execute).run, worker_id="w", max_cycles=2)
        assert started.wait(1)
        # Observe progress without relying on the execution completion/ACK.
        from time import monotonic, sleep

        deadline = monotonic() + 1
        while "consumer-drained" not in log and log.count("control") < 2 and monotonic() < deadline:
            sleep(0.005)
        assert "control" in log and "cleanup" in log and not running.done()
        finish.set()
        result = running.result(2)
    assert result.executed_session_ids == (str(lease.session_id),)
    assert log.index("real-execution-finished") < log.index("consumer-drained")


def test_consume_only_uses_diagnostic_publisher_and_closes_it_after_drain(wired):
    log, *_ = wired
    config = CommandDeliverySettings(
        consume_enabled=True,
        relay_url="amqp://u:p@localhost:5672/v",
        consumer_url="amqp://u:c@localhost:5672/v",
        tick_seconds=0.05,
    )
    _process(wired, config).run(worker_id="w", max_cycles=2)
    assert "diagnostic-publish" in log and "command-publish" not in log
    assert ("consume", module.QUEUE) in log
    assert ("consume", module.SHADOW_QUEUE) not in log
    assert (
        log.index("stop-consuming") < log.index("consumer-drained") < log.index("transport-close")
    )


def test_scoped_rollout_uses_separate_shadow_transport(wired):
    log, *_ = wired
    config = CommandDeliverySettings(
        publish_enabled=True,
        consume_enabled=True,
        scoped_rollout_enabled=True,
        relay_url="amqp://relay:p@localhost:5672/v",
        consumer_url="amqp://consumer:p@localhost:5672/v",
        shadow_consumer_url="amqp://shadow:p@localhost:5672/v",
        tick_seconds=0.05,
    )
    _process(wired, config).run(worker_id="w", max_cycles=2)
    assert log.count("transport-created") == 3
    assert ("consume", module.QUEUE) in log
    assert ("consume", module.SHADOW_QUEUE) in log


def test_broker_down_keeps_fallback_and_safe_logs(wired, caplog):
    log, _, lease, factory = wired

    class Down(factory):
        async def start(self):
            raise RuntimeError("amqp://u:SECRET@unavailable:5672/v")

    config = CommandDeliverySettings(
        consume_enabled=True,
        relay_url="amqp://u:p@localhost:5672/v",
        consumer_url="amqp://u:c@localhost:5672/v",
        tick_seconds=0.05,
    )
    result = _process(wired, config, transport=Down).run(worker_id="w", max_cycles=2)
    assert result.executed_session_ids == (str(lease.session_id),)
    assert "SECRET" not in caplog.text and "command_background_tick_failed" in caplog.text


def test_worker_main_closes_model_client_after_real_process_drain_and_hides_dsn(
    wired, monkeypatch, capsys
):
    import importlib

    main_module = importlib.import_module("zebra_agent_worker.main")
    log, *_ = wired
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": "cloud",
            "ZEBRA_DATABASE_URL": "postgresql://u:SECRET@localhost/db",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            log.append("model-client-close")

    process = _process(wired)
    monkeypatch.setattr(main_module, "load_settings", lambda: settings)
    monkeypatch.setattr(main_module.httpx, "Client", Client)
    monkeypatch.setattr(main_module, "build_worker_loop_service", lambda **kwargs: process)
    assert main_module.main(["--max-cycles", "1"]) == 0
    assert (
        log.index("consumer-drained")
        < log.index("memory-drained")
        < log.index("model-client-close")
    )
    output = capsys.readouterr().out
    assert "SECRET" not in output and "postgresql:[redacted]" in output


def test_recovery_keysets_both_lanes_and_deduplicates_only_verified_scopes(monkeypatch):
    from agent_core.contracts.broker_envelope import PrincipalScope
    from zebra_agent_worker import command_process_state as state

    scope = PrincipalScope(kind="principal", tenant_id="t", workspace_id="w")
    rows = [SimpleNamespace(accepted_event_id=uuid4(), cursor=object()) for _ in range(2)]
    discoveries, recoveries = [], []

    def discover(dsn, **kwargs):
        discoveries.append(kwargs)
        return tuple(rows) if kwargs["after"] is None else ()

    monkeypatch.setattr(state, "discover_command_pickups", discover)
    monkeypatch.setattr(
        state, "resolve_command_pickup", lambda *args, **kwargs: SimpleNamespace(scope=scope)
    )
    monkeypatch.setattr(
        state, "recover_command_batch", lambda *args, **kwargs: recoveries.append(kwargs)
    )
    sweep = state.CommandRecoverySweep("same-dsn", "same-namespace", 2)
    sweep.tick()
    assert len(recoveries) == 1 and recoveries[0]["scope"] == scope
    assert {row["lane"] for row in discoveries} == {"execution", "control"}
    sweep.tick()
    assert len(recoveries) == 1
    assert all(row["after"] is rows[-1].cursor for row in discoveries[2:])


@pytest.mark.parametrize("interrupt", ["signal", "cancel", "cancel_twice"])
def test_shutdown_does_not_cancel_real_execution_future(wired, monkeypatch, interrupt):
    import signal

    log, *_ = wired
    started, finish = Event(), Event()

    def execute(*args, **kwargs):
        started.set()
        assert finish.wait(2)
        log.append("real-finished")

    async def check():
        loop = asyncio.get_running_loop()
        handlers = {}
        monkeypatch.setattr(
            loop, "add_signal_handler", lambda signum, callback: handlers.update({signum: callback})
        )
        monkeypatch.setattr(loop, "remove_signal_handler", lambda signum: True)
        process = _process(wired, execute=execute)
        task = asyncio.create_task(process._run("w", 30, None, False))
        assert await asyncio.to_thread(started.wait, 1)
        if interrupt == "signal":
            handlers[signal.SIGTERM]()
        else:
            task.cancel()
        await asyncio.sleep(0.03)
        assert not task.done() and "consumer-drained" not in log
        if interrupt == "cancel_twice":
            task.cancel()
            await asyncio.sleep(0.03)
            assert not task.done()
        finish.set()
        if interrupt in {"cancel", "cancel_twice"}:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).stop_reason == "signal"

    asyncio.run(check())
    assert log.index("real-finished") < log.index("consumer-drained") < log.index("memory-drained")


def test_signal_during_real_consumer_page_stops_second_candidate(wired, monkeypatch):
    import signal
    from datetime import UTC, datetime

    from agent_runtime import command_wakeup_consumer as runtime
    from agent_storage.postgres.command_wakeup_discovery import PendingCursor
    from agent_storage.postgres.command_wakeup_pickup import CommandPickup

    from tests.agent_runtime.test_command_wakeup_consumer import _fixture

    event, _, _ = _fixture(monkeypatch)
    ids = [event.event_id, uuid4()]
    rows = tuple(CommandPickup(key, PendingCursor(datetime.now(UTC), key)) for key in ids)
    monkeypatch.setattr(
        runtime,
        "discover_command_pickups",
        lambda *args, **kw: rows if kw["lane"] == "execution" else (),
    )
    entered, handlers = [], {}

    def consumer(*args, **kwargs):
        instance = runtime.CommandWakeupConsumer(*args, **kwargs)
        original = instance._handle

        async def handle(key, raw, **options):
            entered.append(key)
            result = await original(key, raw, **options)
            if key == ids[0]:
                handlers[signal.SIGTERM]()
            return result

        instance._handle = handle
        return instance

    monkeypatch.setattr(module, "CommandWakeupConsumer", consumer)

    async def check():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(
            loop, "add_signal_handler", lambda sig, callback: handlers.update({sig: callback})
        )
        monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: True)
        result = await _process(wired)._run("worker", 30, 2, False)
        assert result.stop_reason == "signal"

    asyncio.run(check())
    assert entered == [ids[0]]


def test_cli_batch_and_idle_values_are_effective_with_configured_ceiling(wired, monkeypatch):
    _, objects, *_ = wired
    timeouts = []
    original = asyncio.wait_for

    async def observed(awaitable, timeout):
        timeouts.append(timeout)
        return await original(awaitable, timeout)

    monkeypatch.setattr(module.asyncio, "wait_for", observed)
    process = _process(wired)
    process.run(worker_id="w", batch_size=3, idle_sleep_seconds=0.07, max_cycles=2)
    assert objects[0].options["batch_size"] == 3
    assert (
        0.07 in timeouts and 0.05 in timeouts
    )  # CLI execution cadence; config maintenance cadence
    with pytest.raises(ValueError, match="batch limit"):
        process.run(worker_id="w", batch_size=17, max_cycles=1)
