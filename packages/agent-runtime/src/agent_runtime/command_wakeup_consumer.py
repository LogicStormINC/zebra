"""Explicit bounded consumer ticks; no process activation or runtime cleanup here."""

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from enum import StrEnum
from functools import partial
from threading import BoundedSemaphore, Lock
from typing import Literal, Protocol
from uuid import UUID

from agent_core.contracts.broker_diagnostic import RejectionCode
from agent_core.contracts.broker_envelope import (
    Namespace,
    ZebraCommandEnvelope,
    parse_broker_envelope,
)
from agent_core.domain.leases import WorkerLease
from agent_storage.postgres.command_wakeup_control import ControlStatus, handle_control_command
from agent_storage.postgres.command_wakeup_discovery import PendingCursor
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus, handoff_command
from agent_storage.postgres.command_wakeup_pickup import (
    CONTROL_KINDS,
    PickupLane,
    ResolvedCommand,
    discover_command_pickups,
    resolve_command_pickup,
)
from pydantic import TypeAdapter, ValidationError


class CommandDelivery(Protocol):
    @property
    def body(self) -> bytes: ...
    async def ack(self) -> None: ...
    async def requeue(self) -> None: ...


class PickupOutcome(StrEnum):
    SCHEDULED = "scheduled"
    ACKNOWLEDGED = "acknowledged"
    DEFERRED = "deferred"
    QUARANTINED = "quarantined"


class _Busy(Exception):
    pass


class _SchedulingFailed(RuntimeError):
    """A committed handoff could not be scheduled; preserve its recovery evidence."""


RequiredScopeMode = Literal["broker", "fallback"]
PickupScopeMode = Literal["all", "fallback"]


class CommandWakeupConsumer:
    """Supply execute_claimed_session and an independently durable quarantine callback.

    ACK is transport settlement, not execution completion. After an accepted
    handoff whose scheduling fails, the existing lease/recovery protocol remains
    authoritative. No new acquire or manufactured completion is attempted.
    Quarantine receives an optional untrusted lookup hint, not a validated
    identity: its implementation must not persist that hint as authority.
    """

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        owner: str,
        execute_claimed: Callable[[WorkerLease], object],
        quarantine: Callable[[bytes | None, UUID | None, RejectionCode], Awaitable[None]],
        execution_slots: int = 4,
        batch_size: int = 16,
        lease_ttl: timedelta = timedelta(seconds=30),
        requeue_delay: float = 0.25,
        scoped_rollout: bool = False,
    ) -> None:
        try:
            TypeAdapter(Namespace).validate_python(deployment_namespace)
            TypeAdapter(Namespace).validate_python(owner)
        except ValidationError:
            raise ValueError("invalid consumer namespace or owner") from None
        if (
            type(execution_slots) is not int
            or not 1 <= execution_slots <= 32
            or type(batch_size) is not int
            or not 1 <= batch_size <= 100
            or not isinstance(lease_ttl, timedelta)
            or not timedelta(0) < lease_ttl <= timedelta(minutes=5)
            or owner != owner.strip()
            or type(requeue_delay) not in (int, float)
            or not 0.05 <= requeue_delay <= 5
            or type(scoped_rollout) is not bool
        ):
            raise ValueError("invalid bounded consumer settings")
        self._dsn, self._namespace, self._owner = dsn, deployment_namespace, owner
        self._execute, self._quarantine = execute_claimed, quarantine
        self._batch, self._ttl = batch_size, lease_ttl
        self._requeue_delay = requeue_delay
        self._scoped_rollout = scoped_rollout
        self._slots = BoundedSemaphore(execution_slots)
        self._execution = ThreadPoolExecutor(execution_slots, thread_name_prefix="command-execute")
        self._admission = ThreadPoolExecutor(2, thread_name_prefix="command-admit")
        self._control = ThreadPoolExecutor(2, thread_name_prefix="command-control")
        self._db_slots = {self._admission: BoundedSemaphore(2), self._control: BoundedSemaphore(2)}
        self._lock, self._closed = Lock(), False
        self._cursors: dict[PickupLane, PendingCursor | None] = {"execution": None, "control": None}
        self._polling = {"execution": asyncio.Lock(), "control": asyncio.Lock()}

    async def _db[T](self, pool: ThreadPoolExecutor, function: Callable[[], T]) -> T:
        with self._lock:
            if self._closed or not self._db_slots[pool].acquire(blocking=False):
                raise _Busy
            try:
                future = pool.submit(function)
            except BaseException:
                self._db_slots[pool].release()
                raise
        future.add_done_callback(lambda _: self._db_slots[pool].release())
        # A cancelled await never cancels a running DB handoff or its scheduling.
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(wrapped)

    def _admit(
        self,
        resolved: ResolvedCommand,
        raw: bytes | None,
        required_scope_mode: RequiredScopeMode | None = None,
    ) -> PickupOutcome:
        if not self._slots.acquire(blocking=False):
            return PickupOutcome.DEFERRED
        scheduled = False
        try:
            result = handoff_command(
                self._dsn,
                deployment_namespace=self._namespace,
                scope=resolved.scope,
                accepted_event_id=resolved.accepted_event_id,
                owner_instance_id=self._owner,
                ttl=self._ttl,
                raw_body=raw,
                required_scope_mode=required_scope_mode,
            )
            if result.status in {
                HandoffStatus.DUPLICATE,
                HandoffStatus.RETIRED_NOOP,
                HandoffStatus.REQUIRES_RECONCILIATION,
                HandoffStatus.SCOPE_SETTLED,
            }:
                return PickupOutcome.ACKNOWLEDGED
            if result.status is not HandoffStatus.ACCEPTED:
                return PickupOutcome.DEFERRED
            assert result.lease is not None
            try:
                future = self._execution.submit(self._execute, result.lease)
            except Exception:
                raise _SchedulingFailed("committed command scheduling failed") from None
            scheduled = True
            # Slot release follows the real synchronous Future, never task cancellation.
            future.add_done_callback(self._execution_finished)
            return PickupOutcome.SCHEDULED
        finally:
            if not scheduled:
                self._slots.release()

    def _execution_finished(self, future: Future[object]) -> None:
        try:
            if not future.cancelled():
                future.exception()  # do not log model/credential exception text
        finally:
            self._slots.release()

    async def _handle(
        self,
        accepted_id: UUID,
        raw: bytes | None,
        *,
        control_lane: bool = False,
        scope_mode: RequiredScopeMode | None = None,
    ) -> PickupOutcome:
        pool = self._control if control_lane else self._admission
        resolved = await self._db(
            pool,
            partial(
                resolve_command_pickup,
                self._dsn,
                deployment_namespace=self._namespace,
                accepted_event_id=accepted_id,
            ),
        )
        if resolved.kind in CONTROL_KINDS:
            control = await self._db(
                self._control,
                partial(
                    handle_control_command,
                    self._dsn,
                    deployment_namespace=self._namespace,
                    scope=resolved.scope,
                    accepted_event_id=accepted_id,
                    raw_body=raw,
                    required_scope_mode=scope_mode,
                ),
            )
            if getattr(control, "status", None) is ControlStatus.SCOPE_DEFERRED:
                return PickupOutcome.DEFERRED
            return PickupOutcome.ACKNOWLEDGED
        return await self._db(
            self._admission,
            partial(self._admit, resolved, raw, scope_mode),
        )

    async def on_delivery(self, delivery: CommandDelivery) -> PickupOutcome:
        """Suitable for RabbitMQTransport.consume; never trusts the envelope scope."""
        accepted_id = None
        try:
            envelope = parse_broker_envelope(delivery.body)
            if not isinstance(envelope, ZebraCommandEnvelope):
                raise ValueError("not a command envelope")
            accepted_id = UUID(envelope.accepted_event_id)
            outcome = await self._handle(
                accepted_id,
                delivery.body,
                scope_mode="broker" if self._scoped_rollout else None,
            )
        except (ValueError, TypeError):
            try:
                await self._quarantine(
                    delivery.body,
                    accepted_id,
                    "invalid_broker_envelope" if accepted_id is None else "broker_hint_conflict",
                )
            except Exception:
                await self._requeue(delivery)
                return PickupOutcome.DEFERRED
            await delivery.ack()
            return PickupOutcome.QUARANTINED
        except Exception:
            await self._requeue(delivery)
            return PickupOutcome.DEFERRED
        if outcome is PickupOutcome.DEFERRED:
            await self._requeue(delivery)
        else:
            await delivery.ack()
        return outcome

    async def _requeue(self, delivery: CommandDelivery) -> None:
        # Holding broker credit briefly bounds transient redelivery churn. The
        # independent control tick does not depend on these credits or this wait.
        await asyncio.sleep(self._requeue_delay)
        await delivery.requeue()

    async def poll(
        self,
        lane: PickupLane,
        *,
        scope_mode: PickupScopeMode = "all",
    ) -> tuple[PickupOutcome, ...]:
        """One bounded fallback page. Call control ticks independently of execution ticks."""
        if lane not in ("execution", "control"):
            raise ValueError("invalid consumer lane")
        if scope_mode not in ("all", "fallback"):
            raise ValueError("invalid consumer scope mode")
        if self._polling[lane].locked():
            return ()
        async with self._polling[lane]:
            pool = self._control if lane == "control" else self._admission
            try:
                rows = await self._db(
                    pool,
                    partial(
                        discover_command_pickups,
                        self._dsn,
                        deployment_namespace=self._namespace,
                        lane=lane,
                        batch_size=self._batch,
                        after=self._cursors[lane],
                        scope_mode=scope_mode,
                    ),
                )
            except _Busy:
                return ()
            if not rows:
                self._cursors[lane] = None
                return ()
            outcomes = []
            for row in rows:
                with self._lock:
                    if self._closed:
                        break
                try:
                    outcome = await self._handle(
                        row.accepted_event_id,
                        None,
                        control_lane=lane == "control",
                        scope_mode=None if scope_mode == "all" else "fallback",
                    )
                except (ValueError, TypeError):
                    try:
                        await self._quarantine(None, row.accepted_event_id, "broker_hint_conflict")
                    except Exception:
                        # An unprovable poison hint cannot stop later candidates.
                        # No ACK or isolation is claimed; keyset wrap retries it.
                        outcome = PickupOutcome.DEFERRED
                    else:
                        outcome = PickupOutcome.QUARANTINED
                except _Busy:
                    break
                outcomes.append(outcome)
                self._cursors[lane] = row.cursor
            return tuple(outcomes)

    def stop_new_admissions(self) -> None:
        """Linearize refusal of new DB work without cancelling already submitted Futures."""
        with self._lock:
            self._closed = True

    async def close(self) -> None:
        """Stop new admissions and drain real DB/execution work; cancellation cannot free slots."""
        self.stop_new_admissions()

        def drain() -> None:
            self._admission.shutdown(wait=True, cancel_futures=False)
            self._control.shutdown(wait=True, cancel_futures=False)
            self._execution.shutdown(wait=True, cancel_futures=False)

        await asyncio.to_thread(drain)
