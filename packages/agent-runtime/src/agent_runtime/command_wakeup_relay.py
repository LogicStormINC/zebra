"""Explicit bounded relay tick; composition must inject a confirmed publisher."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Literal

from agent_storage.postgres.command_wakeup_relay import (
    MAX_RELAY_BATCH,
    RelayClaim,
    claim_relay_batch,
    settle_relay_claim,
)


async def relay_command_batch(
    dsn: str,
    *,
    deployment_namespace: str,
    owner: str,
    publish_confirmed: Callable[[bytes], Awaitable[None]],
    batch_size: int = 16,
    publish_timeout: float = 10.0,
    lease_ttl: timedelta = timedelta(seconds=30),
    scope_mode: Literal["all", "broker"] = "all",
) -> int:
    """Publish outside DB transactions; return successfully fenced confirmations.

    Supply functools.partial(RabbitMQTransport.publish, exchange=..., routing_key=...).
    Cancellation intentionally leaves the publishing lease for bounded reclamation;
    asyncio.to_thread cannot interrupt a DB operation already running in a thread.
    """
    if (
        type(batch_size) is not int
        or not 1 <= batch_size <= MAX_RELAY_BATCH
        or type(publish_timeout) not in (int, float)
        or not math.isfinite(publish_timeout)
        or not 0 < publish_timeout <= 60
        or not isinstance(lease_ttl, timedelta)
        or not timedelta(seconds=publish_timeout) < lease_ttl <= timedelta(minutes=5)
    ):
        raise ValueError("invalid bounded relay settings")
    claims = await asyncio.to_thread(
        claim_relay_batch,
        dsn,
        deployment_namespace=deployment_namespace,
        owner=owner,
        batch_size=batch_size,
        ttl=lease_ttl,
        scope_mode=scope_mode,
    )

    async def publish(claim: RelayClaim) -> int:
        confirmed = False
        try:
            async with asyncio.timeout(publish_timeout):
                await publish_confirmed(claim.body)
            confirmed = True
        except Exception:
            # Never persist transport exception text, credentials or payloads.
            pass
        settled = await asyncio.to_thread(settle_relay_claim, dsn, claim, confirmed=confirmed)
        return int(confirmed and settled)

    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(publish(claim)) for claim in claims]
    return sum(task.result() for task in tasks)
