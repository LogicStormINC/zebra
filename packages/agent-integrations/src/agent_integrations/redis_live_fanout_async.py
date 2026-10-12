"""Instance-owned async notification reads; no default-executor blocking XREAD."""

import asyncio
from collections.abc import Mapping
from typing import Any, cast

from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.exceptions import ResponseError
from redis.retry import Retry


class AsyncRedisNotifications:
    def __init__(self, url: str, *, key_prefix: str = "zebra:live:v1") -> None:
        self.key_prefix = key_prefix
        self.client: Redis = Redis.from_url(
            url,
            decode_responses=True,
            max_connections=128,
            socket_connect_timeout=1,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        )

    def key(self, namespace: str, resource: object, *, checkpoint: bool = False) -> str:
        suffix = ":checkpoint" if checkpoint else ""
        return f"{self.key_prefix}:{namespace.encode().hex()}:{resource}{suffix}"

    async def barrier(self, key: str) -> str:
        try:
            async with asyncio.timeout(0.25):
                info = await self.client.xinfo_stream(key)
        except ResponseError as exc:
            if "no such key" in str(exc).lower():
                return "0-0"
            raise
        return str(info["last-generated-id"])

    async def wait(self, positions: Mapping[str, str], *, block_ms: int = 1000) -> dict[str, str]:
        if not 1 <= len(positions) <= 4 or not 1 <= block_ms <= 1000:
            raise ValueError("notification read exceeds its bounds")
        rows = await self.client.xread(cast(Any, dict(positions)), count=100, block=block_ms)
        result = dict(positions)
        for key, entries in rows:
            if entries:
                result[str(key)] = str(entries[-1][0])
        return result

    async def close(self) -> None:
        await self.client.aclose()
