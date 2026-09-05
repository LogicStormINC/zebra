"""Confirmed sanitized quarantine callback and one-item recovery sweep."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID, uuid4

from agent_core.contracts.broker_diagnostic import RejectionCode
from agent_core.contracts.broker_envelope import Namespace
from agent_storage.postgres.command_wakeup_quarantine import (
    RejectionClaim,
    claim_rejection,
    record_rejection,
    settle_rejection,
    validate_rejection_metadata,
)
from agent_storage.postgres.command_wakeup_quarantine_candidate import quarantine_candidate
from pydantic import TypeAdapter


class CommandQuarantineError(RuntimeError):
    """No ACK: diagnostic persistence/confirmation/settlement is incomplete."""


class CommandWakeupQuarantine:
    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        publish_confirmed: Callable[..., Awaitable[object]],
        consumer_role: str = "zebra.session.command",
        publish_timeout: float = 10.0,
        lease_ttl: timedelta = timedelta(seconds=30),
    ) -> None:
        try:
            TypeAdapter(Namespace).validate_python(deployment_namespace)
            validate_rejection_metadata(consumer_role, "invalid_broker_envelope")
        except ValueError:
            raise ValueError("invalid quarantine namespace or role") from None
        if (
            type(publish_timeout) not in (int, float)
            or not 0 < publish_timeout <= 60
            or not isinstance(lease_ttl, timedelta)
            or not timedelta(seconds=publish_timeout) < lease_ttl <= timedelta(minutes=5)
        ):
            raise ValueError("invalid quarantine time bounds")
        self._dsn, self._namespace, self._role = dsn, deployment_namespace, consumer_role
        self._publisher, self._timeout, self._ttl = publish_confirmed, publish_timeout, lease_ttl

    async def __call__(
        self, raw: bytes | None, accepted_id: UUID | None, code: RejectionCode
    ) -> None:
        try:
            if raw is None:
                if accepted_id is None:
                    raise CommandQuarantineError("missing fallback lookup hint")
                receipt = await asyncio.to_thread(
                    quarantine_candidate,
                    self._dsn,
                    deployment_namespace=self._namespace,
                    consumer_role=self._role,
                    accepted_event_id=accepted_id,
                    code=code,
                )
            else:
                # Never inspect or persist an accepted_id supplied by a raw broker delivery.
                receipt = await asyncio.to_thread(
                    record_rejection,
                    self._dsn,
                    deployment_namespace=self._namespace,
                    consumer_role=self._role,
                    raw=raw,
                    code=code,
                )
            if receipt is None or receipt.published:
                return
            claim = await self._claim(receipt.rejection_id)
            if claim is None:
                raise CommandQuarantineError("diagnostic pending recovery")
            await self._publish(claim)
        except Exception:
            raise CommandQuarantineError("command quarantine incomplete") from None

    async def _claim(self, rejection_id: UUID | None = None) -> RejectionClaim | None:
        return await asyncio.to_thread(
            claim_rejection,
            self._dsn,
            deployment_namespace=self._namespace,
            consumer_role=self._role,
            owner=f"quarantine-{uuid4()}",
            ttl=self._ttl,
            rejection_id=rejection_id,
        )

    async def _publish(self, claim: RejectionClaim) -> None:
        try:
            async with asyncio.timeout(self._timeout):
                result = await self._publisher(
                    claim.body,
                    exchange="zebra.command.diagnostic.x",
                    routing_key="delivery.rejected.v1",
                )
                if result is False:
                    raise CommandQuarantineError("diagnostic not confirmed")
        except Exception:
            await asyncio.to_thread(settle_rejection, self._dsn, claim, confirmed=False)
            raise CommandQuarantineError("diagnostic publication failed") from None
        if not await asyncio.to_thread(settle_rejection, self._dsn, claim, confirmed=True):
            raise CommandQuarantineError("diagnostic settlement lost")

    async def publish_once(self) -> bool:
        """Bounded durable pending/expired-claim retry independent of raw redelivery."""
        try:
            claim = await self._claim()
            if claim is None:
                return False
            await self._publish(claim)
            return True
        except Exception:
            raise CommandQuarantineError("command quarantine recovery incomplete") from None
