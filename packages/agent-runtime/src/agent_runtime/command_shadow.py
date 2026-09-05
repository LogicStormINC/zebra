"""Physically separate side-effect-free command shadow relay and consumer."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol

from agent_storage.postgres.command_rollout_shadow import (
    claim_command_shadow_batch,
    observe_command_shadow,
    reject_command_shadow,
    settle_command_shadow,
)


class ShadowDelivery(Protocol):
    @property
    def body(self) -> bytes: ...
    async def ack(self) -> None: ...
    async def requeue(self) -> None: ...


async def relay_command_shadow_batch(
    dsn: str,
    *,
    deployment_namespace: str,
    owner: str,
    publish_confirmed: Callable[[bytes], Awaitable[None]],
    batch_size: int = 16,
    publish_timeout: float = 10.0,
) -> int:
    """Publish exact formal envelopes; settle only after broker confirmation."""
    claims = await asyncio.to_thread(
        claim_command_shadow_batch,
        dsn,
        deployment_namespace=deployment_namespace,
        owner=owner,
        batch_size=batch_size,
        ttl=timedelta(seconds=max(2.0, publish_timeout * 2)),
    )
    published = 0
    for claim in claims:
        confirmed = False
        try:
            async with asyncio.timeout(publish_timeout):
                await publish_confirmed(claim.body)
            confirmed = True
        except Exception:
            pass
        settled = await asyncio.to_thread(settle_command_shadow, dsn, claim, confirmed=confirmed)
        if confirmed and settled:
            published += 1
    return published


async def consume_command_shadow(
    delivery: ShadowDelivery,
    *,
    dsn: str,
    deployment_namespace: str,
) -> None:
    """Observe only; malformed input is durably digested before transport ACK."""
    try:
        await asyncio.to_thread(
            observe_command_shadow,
            dsn,
            deployment_namespace=deployment_namespace,
            body=delivery.body,
        )
    except ValueError:
        try:
            await asyncio.to_thread(
                reject_command_shadow,
                dsn,
                deployment_namespace=deployment_namespace,
                body=delivery.body,
            )
        except Exception:
            await delivery.requeue()
            return
    except Exception:
        await delivery.requeue()
        return
    await delivery.ack()
