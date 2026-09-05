"""Explicit migrated worker process: bounded lanes and real-work shutdown drain."""

import asyncio
import logging
import math
import signal
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import partial
from threading import Lock
from typing import Any

from agent_core.domain.leases import WorkerLease
from agent_runtime.command_runtime_cleanup import cleanup_runtime_batch
from agent_runtime.command_shadow import consume_command_shadow, relay_command_shadow_batch
from agent_runtime.command_wakeup_consumer import (
    CommandDelivery,
    CommandWakeupConsumer,
    PickupOutcome,
)
from agent_runtime.command_wakeup_quarantine import CommandWakeupQuarantine
from agent_runtime.command_wakeup_relay import relay_command_batch
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.command_process_state import CommandRecoverySweep
from zebra_agent_worker.runtime_factory import pin_cloud_engine
from zebra_agent_worker.worker_loop_service import WorkerLoopRunResult
from zebra_agent_worker.worker_polling import validate_loop_inputs

logger = logging.getLogger(__name__)
QUEUE = "zebra.session.command.ready.q"
SHADOW_QUEUE = "zebra.session.command.ready.shadow.q"


class CommandWorkerProcess:
    def __init__(
        self,
        *,
        dsn: str,
        namespace: str,
        settings: ZebraAgentSettings,
        execute: Callable[..., object],
        maintenance: Callable[..., None],
        drain: Callable[[], None],
        transport_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._dsn, self._namespace, self._settings = dsn, namespace, settings
        self._execute, self._maintenance, self._drain = execute, maintenance, drain
        self._transport_factory = transport_factory
        self._muted: list[tuple[logging.Logger, bool]] = []

    def run(
        self,
        *,
        worker_id: str,
        batch_size: int = 1,
        lease_ttl_seconds: int = 30,
        max_cycles: int | None = None,
        stop_when_idle: bool = False,
        idle_sleep_seconds: float = 0.1,
    ) -> WorkerLoopRunResult:
        validate_loop_inputs(
            batch_size=batch_size,
            lease_ttl_seconds=lease_ttl_seconds,
            max_cycles=max_cycles,
            idle_sleep_seconds=idle_sleep_seconds,
        )
        try:
            if (
                type(batch_size) is not int
                or batch_size > self._settings.command_delivery.batch_size
            ):
                raise ValueError("worker batch exceeds configured command batch limit")
            if (
                type(idle_sleep_seconds) not in (int, float)
                or not math.isfinite(idle_sleep_seconds)
                or not 0 <= idle_sleep_seconds <= 30
            ):
                raise ValueError("worker idle interval is outside bounds")
            return asyncio.run(
                self._run(
                    worker_id,
                    lease_ttl_seconds,
                    max_cycles,
                    stop_when_idle,
                    batch_size=batch_size,
                    idle_sleep_seconds=idle_sleep_seconds,
                )
            )
        finally:
            for log, disabled in self._muted:
                log.disabled = disabled
            self._muted.clear()

    async def _run(
        self,
        owner: str,
        ttl: int,
        max_cycles: int | None,
        stop_when_idle: bool,
        *,
        batch_size: int | None = None,
        idle_sleep_seconds: float | None = None,
    ) -> WorkerLoopRunResult:
        config = self._settings.command_delivery
        stop = asyncio.Event()
        consumer: CommandWakeupConsumer | None = None

        def stop_new_work() -> None:
            stop.set()
            if consumer is not None:
                consumer.stop_new_admissions()

        loop = asyncio.get_running_loop()
        signals = []
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop_new_work)
                signals.append(signum)
            except (NotImplementedError, RuntimeError, ValueError):
                pass  # Embedded test threads do not own process signals.
        publisher = subscriber = shadow_subscriber = None
        if config.publish_enabled or config.consume_enabled:
            factory = self._transport_factory
            if factory is None:
                from agent_integrations.rabbitmq import RabbitMQTransport

                factory = RabbitMQTransport
            # Connection diagnostics may contain credentials; retain fixed application codes.
            for name in {"aio_pika", "aiormq", "pamqp", *logging.Logger.manager.loggerDict}:
                if name.split(".", 1)[0] in {"aio_pika", "aiormq", "pamqp"}:
                    log = logging.getLogger(name)
                    self._muted.append((log, log.disabled))
                    log.disabled = True
            assert config.relay_url is not None
            publisher = factory(
                config.relay_url, prefetch=config.batch_size, timeout=config.transport_timeout
            )
            if config.consume_enabled:
                assert config.consumer_url is not None
                subscriber = factory(
                    config.consumer_url,
                    prefetch=config.batch_size,
                    timeout=config.transport_timeout,
                )
            if config.scoped_rollout_enabled:
                assert config.shadow_consumer_url is not None
                shadow_subscriber = factory(
                    config.shadow_consumer_url,
                    prefetch=config.batch_size,
                    timeout=config.transport_timeout,
                )

        async def diagnostic(body: bytes, **routing: str) -> None:
            if publisher is None:
                raise RuntimeError("diagnostic publishing is disabled")
            await publisher.start()
            await publisher.publish_diagnostic(body, **routing)

        async def publish(body: bytes) -> None:
            assert publisher is not None
            await publisher.start()
            await publisher.publish(
                body, exchange="zebra.command.x", routing_key="session.command.ready.v1"
            )

        async def publish_shadow(body: bytes) -> None:
            assert publisher is not None
            await publisher.start()
            await publisher.publish(
                body,
                exchange="zebra.command.shadow.x",
                routing_key="session.command.ready.shadow.v1",
            )

        completed: list[str] = []
        failed: list[str] = []
        execution_lock = Lock()
        running = 0

        def execute(lease: WorkerLease) -> object:
            nonlocal running
            with execution_lock:
                running += 1
            try:
                result = self._execute(lease, lease_ttl_seconds=ttl)
            except Exception:
                with execution_lock:
                    failed.append(str(lease.session_id))
                logger.warning("command_execution_failed")
                raise
            else:
                with execution_lock:
                    completed.append(str(lease.session_id))
                return result
            finally:
                with execution_lock:
                    running -= 1

        quarantine = CommandWakeupQuarantine(
            self._dsn,
            deployment_namespace=self._namespace,
            publish_confirmed=diagnostic,
            publish_timeout=config.transport_timeout,
        )
        consumer = CommandWakeupConsumer(
            self._dsn,
            deployment_namespace=self._namespace,
            owner=owner,
            execute_claimed=execute,
            quarantine=quarantine,
            execution_slots=config.execution_slots,
            batch_size=config.batch_size if batch_size is None else batch_size,
            lease_ttl=timedelta(seconds=ttl),
            scoped_rollout=config.scoped_rollout_enabled,
        )
        callbacks: set[asyncio.Task[Any]] = set()
        tag: str | None = None
        shadow_tag: str | None = None

        async def delivery(message: CommandDelivery) -> None:
            if stop.is_set():
                return  # No ACK; consumer cancellation/channel close returns delivery ownership.
            task = asyncio.current_task()
            assert task is not None
            callbacks.add(task)
            try:
                await consumer.on_delivery(message)
            finally:
                callbacks.discard(task)

        async def shadow_delivery(message: CommandDelivery) -> None:
            if stop.is_set():
                return
            task = asyncio.current_task()
            assert task is not None
            callbacks.add(task)
            try:
                await consume_command_shadow(
                    message,
                    dsn=self._dsn,
                    deployment_namespace=self._namespace,
                )
            finally:
                callbacks.discard(task)

        async def subscribe() -> None:
            nonlocal shadow_tag, tag
            if subscriber is not None and tag is None:
                await subscriber.start()
                tag = await subscriber.consume(QUEUE, delivery)
            if shadow_subscriber is not None and shadow_tag is None:
                await shadow_subscriber.start()
                shadow_tag = await shadow_subscriber.consume(SHADOW_QUEUE, shadow_delivery)

        recovery = CommandRecoverySweep(
            self._dsn,
            self._namespace,
            config.batch_size,
            scope_mode="fallback" if config.scoped_rollout_enabled else "all",
        )
        maintenance_pool = ThreadPoolExecutor(1, thread_name_prefix="command-maintenance")
        cleanup_pool = ThreadPoolExecutor(1, thread_name_prefix="command-cleanup")
        engine = None

        def cleanup() -> None:
            nonlocal engine
            engine = engine or pin_cloud_engine(self._settings)
            cleanup_runtime_batch(
                self._dsn,
                deployment_namespace=self._namespace,
                owner=owner,
                engine=engine,
                engine_command=self._settings.runtime.engine,
                batch_size=1,
            )

        async def background(action: Callable[[], Awaitable[object]]) -> None:
            delay = config.tick_seconds
            while not stop.is_set():
                try:
                    await action()
                except Exception:
                    logger.warning("command_background_tick_failed")
                    delay = min(30.0, delay * 2)
                else:
                    delay = config.tick_seconds
                try:
                    await asyncio.wait_for(stop.wait(), delay)
                except TimeoutError:
                    pass

        async def maintenance() -> None:
            await loop.run_in_executor(
                maintenance_pool,
                partial(
                    self._maintenance,
                    worker_id=owner,
                    batch_size=config.batch_size,
                    lease_ttl_seconds=ttl,
                ),
            )
            if not stop.is_set():
                await loop.run_in_executor(maintenance_pool, recovery.tick)

        jobs = [
            asyncio.create_task(background(maintenance)),
            asyncio.create_task(background(lambda: loop.run_in_executor(cleanup_pool, cleanup))),
        ]
        # Canonical controls always have a separate DB lane, even with broker-only execution.
        jobs.append(
            asyncio.create_task(
                background(
                    lambda: consumer.poll(
                        "control",
                        scope_mode="fallback" if config.scoped_rollout_enabled else "all",
                    )
                )
            )
        )
        if subscriber is not None:
            jobs.append(asyncio.create_task(background(subscribe)))
        if publisher is not None:
            jobs.append(asyncio.create_task(background(quarantine.publish_once)))
        if config.publish_enabled:
            jobs.append(
                asyncio.create_task(
                    background(
                        partial(
                            relay_command_batch,
                            self._dsn,
                            deployment_namespace=self._namespace,
                            owner=owner,
                            publish_confirmed=publish,
                            batch_size=min(config.batch_size, 32),
                            publish_timeout=config.transport_timeout,
                            scope_mode="broker" if config.scoped_rollout_enabled else "all",
                        )
                    )
                )
            )
            if config.scoped_rollout_enabled:
                jobs.append(
                    asyncio.create_task(
                        background(
                            partial(
                                relay_command_shadow_batch,
                                self._dsn,
                                deployment_namespace=self._namespace,
                                owner=owner,
                                publish_confirmed=publish_shadow,
                                batch_size=min(config.batch_size, 32),
                                publish_timeout=config.transport_timeout,
                            )
                        )
                    )
                )
        cycles = idle = 0
        reason = "max_cycles"
        try:
            while not stop.is_set() and (max_cycles is None or cycles < max_cycles):
                outcomes: tuple[PickupOutcome, ...] = ()
                if config.scan_fallback_enabled:
                    try:
                        outcomes = await consumer.poll(
                            "execution",
                            scope_mode="fallback" if config.scoped_rollout_enabled else "all",
                        )
                    except Exception:
                        logger.warning("command_execution_pickup_failed")
                        outcomes = (PickupOutcome.DEFERRED,)
                cycles += 1
                with execution_lock:
                    is_idle = config.scan_fallback_enabled and not outcomes and running == 0
                idle += int(is_idle)
                if stop_when_idle and is_idle:
                    reason = "idle"
                    break
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        config.tick_seconds if idle_sleep_seconds is None else idle_sleep_seconds,
                    )
                except TimeoutError:
                    pass
            if stop.is_set():
                reason = "signal"
        finally:
            stop_new_work()

            async def shutdown() -> None:
                if subscriber is not None:
                    try:
                        if tag is not None:
                            await subscriber.stop_consuming(QUEUE, tag)
                    except Exception:
                        logger.warning("command_consumer_stop_failed")
                if shadow_subscriber is not None:
                    try:
                        if shadow_tag is not None:
                            await shadow_subscriber.stop_consuming(SHADOW_QUEUE, shadow_tag)
                    except Exception:
                        logger.warning("command_shadow_consumer_stop_failed")
                await asyncio.gather(*jobs)
                if callbacks:
                    await asyncio.gather(*tuple(callbacks), return_exceptions=True)
                await (
                    consumer.close()
                )  # real handoff/execute Future drain, never cancellation-as-drain
                await loop.run_in_executor(maintenance_pool, self._drain)
                maintenance_pool.shutdown(wait=True)
                cleanup_pool.shutdown(wait=True)
                for transport in (subscriber, shadow_subscriber, publisher):
                    if transport is not None:
                        try:
                            await transport.close()
                        except Exception:
                            logger.warning("command_transport_close_failed")
                for signum in signals:
                    loop.remove_signal_handler(signum)

            finishing = asyncio.create_task(shutdown())
            cancelled = False
            while True:
                try:
                    await asyncio.shield(finishing)
                    break
                except asyncio.CancelledError:
                    if finishing.cancelled():
                        raise  # An independently cancelled cleanup must not become a busy loop.
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
        return WorkerLoopRunResult(cycles, idle, reason, tuple(completed), tuple(failed))
