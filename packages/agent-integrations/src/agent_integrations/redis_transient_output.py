"""Fenced, bounded Redis temporary drafts; no durable content writes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

from agent_core.domain.stream_admission import TransientCapacityPolicy
from agent_core.domain.transient_output import TransientTextFrame
from agent_core.ports.live_event_fanout import LiveEventCursor
from agent_core.ports.transient_output import (
    TransientOutputBatch,
    TransientResumeCursor,
    TransientStreamScope,
    TransientWriterAuthorization,
)
from redis import ConnectionPool, Redis, RedisCluster
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from agent_integrations.redis_transient_capacity import GC, READ_BOUND, SEAL
from agent_integrations.redis_transient_deadlines import (
    current_redis_io_deadline,
    deadline_redis_options,
    transient_lock,
)
from agent_integrations.redis_transient_discovery import (
    TransientDescriptor,
    transient_aggregates,
    transient_deployment_key,
    transient_lane,
)
from agent_integrations.redis_transient_scripts import ACTIVATE, INVALIDATE, PUBLISH, READ, SNAPSHOT


class TransientOutputUnavailable(RuntimeError):
    """Caller must close provisional output and reconcile the durable response."""


class RedisTransientOutput:
    def __init__(
        self,
        client: Any,
        *,
        resolve_authorization: Callable[[TransientWriterAuthorization], None],
        read_authority: Callable[[TransientStreamScope], datetime] | None = None,
        descriptor_source: Callable[[TransientWriterAuthorization], int] | None = None,
        key_prefix: str = "zebra:transient:v2",
        retention_seconds: int = 3600,
        max_bytes: int = 8 * 1024 * 1024,
        max_rows: int = 8192,
    ) -> None:
        if not key_prefix or key_prefix != key_prefix.strip() or "{" in key_prefix:
            raise ValueError("invalid transient key prefix")
        if not 1 <= retention_seconds <= 3600 or not 1 <= max_bytes <= 8 * 1024 * 1024:
            raise ValueError("invalid transient retention or byte capacity")
        if not 1 <= max_rows <= 8192:
            raise ValueError("invalid transient row capacity")
        if isinstance(client, RedisCluster):
            raise TransientOutputUnavailable("capacity requires standalone Redis")
        self._client, self._resolve = client, resolve_authorization
        self._read_authority = read_authority
        self._descriptor_source = descriptor_source
        self._prefix, self._retention = key_prefix, retention_seconds
        self._max_bytes, self._max_rows = max_bytes, max_rows
        self._active: dict[str, TransientWriterAuthorization] = {}
        self._lock = RLock()

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        resolve_authorization: Callable[[TransientWriterAuthorization], None],
        key_prefix: str = "zebra:transient:v2",
        descriptor_source: Callable[[TransientWriterAuthorization], int] | None = None,
        read_authority: Callable[[TransientStreamScope], datetime] | None = None,
        read_timeout: float = 2,
    ) -> RedisTransientOutput:
        if not 0 < read_timeout <= 2:
            raise ValueError("invalid transient socket deadline")
        return cls(
            Redis(
                connection_pool=ConnectionPool(
                    **{
                        "decode_responses": True,
                        "socket_connect_timeout": min(1, read_timeout),
                        "socket_timeout": read_timeout,
                        "max_connections": 128,
                        "retry": Retry(NoBackoff(), 0),
                        **deadline_redis_options(url),
                    }
                )
            ),
            resolve_authorization=resolve_authorization,
            descriptor_source=descriptor_source,
            read_authority=read_authority,
            key_prefix=key_prefix,
        )

    def _keys(self, scope: TransientStreamScope) -> tuple[str, str, str]:
        generation = scope.generation
        prefix = transient_lane(
            scope.deployment_namespace,
            scope.authority_scope,
            str(generation.task_id),
            str(generation.segment_id),
            generation.run_id,
            key_prefix=self._prefix,
        )
        return (
            f"{prefix}:authority",
            f"{prefix}:{generation.generation_id}:frames",
            f"{prefix}:{generation.generation_id}:offsets",
        )

    def _capacity_keys(self, scope: TransientStreamScope) -> tuple[str, str, str]:
        ledger, _, _ = transient_aggregates(scope, key_prefix=self._prefix)
        record = ledger + ":record:" + sha256(self._keys(scope)[1].encode()).hexdigest()
        return ledger, ledger + ":due", record

    def _eval(
        self, script: str, scope: TransientStreamScope, *args: object,
        policy: TransientCapacityPolicy | None = None,
    ) -> list[str]:
        try:
            keys = self._keys(scope)
            tail: tuple[object, ...] = ()
            if policy is not None:
                _, tenant, run = transient_aggregates(scope, key_prefix=self._prefix)
                tail = (policy.model_dump_json(), policy.digest, tenant, run,
                        scope.generation.generation_id)
            elif script == READ:
                _, tenant, run = transient_aggregates(scope, key_prefix=self._prefix)
                tail = (tenant, run)
                script = READ_BOUND + script
            raw = self._client.eval(
                script, 7, *keys, keys[0] + ":control", *self._capacity_keys(scope),
                *args, *tail,
            )
            return [item.decode() if isinstance(item, bytes) else str(item) for item in raw]
        except (RedisError, OSError) as exc:
            raise TransientOutputUnavailable("temporary output transport unavailable") from exc

    @staticmethod
    def _millis(timestamp: datetime) -> int:
        if timestamp.utcoffset() is None:
            raise ValueError("authority deadline must be timezone-aware")
        return int(timestamp.timestamp() * 1000)

    def activate(self, authorization: TransientWriterAuthorization) -> None:
        with transient_lock(self._lock):
            scope = authorization.scope
            self._resolve(authorization)  # BEFORE the first reservation/quota mutation.
            policy = authorization.capacity_policy
            if policy is None or authorization.capacity_digest != policy.digest:
                raise TransientOutputUnavailable("writer has no frozen capacity policy")
            metadata_keys = (*self._keys(scope), self._keys(scope)[0]+":control",
                             *self._capacity_keys(scope))
            if (any(len(key.encode()) > 512 for key in metadata_keys) or
                    2*sum(len(key.encode()) for key in metadata_keys)+8192+4096 >
                    policy.metadata_bytes):
                raise TransientOutputUnavailable("capacity metadata allowance exceeded")
            if isinstance(self._client, RedisCluster):
                raise TransientOutputUnavailable("capacity requires standalone Redis")
            reserved = self._eval(
                SNAPSHOT, scope, uuid4().hex, self._millis(authorization.expires_at),
                scope.generation.generation_id, policy=policy,
            )
            if reserved[0] != "ok":
                raise TransientOutputUnavailable(f"temporary reservation rejected: {reserved[0]}")
            expected = reserved[1]
            self._resolve(authorization)  # Fresh source/Host/Turn/Lease before ACTIVATE CAS.
            now = datetime.now(UTC)
            if not authorization.issued_at <= now < authorization.expires_at:
                raise TransientOutputUnavailable("writer authority expired")
            scope, fence = authorization.scope, authorization.lease_fence
            key = self._keys(scope)[1]
            renewing = key in self._active
            if not renewing and len(self._active) >= 4096:
                raise TransientOutputUnavailable("process writer capacity exhausted")
            maximum = min(
                self._millis(now) + min(self._retention, policy.active_seconds) * 1000,
                self._millis(authorization.grant_expires_at),
            )
            result = self._eval(
                ACTIVATE,
                scope,
                scope.generation.generation_id,
                str(fence.control_plane_epoch),
                fence.fencing_token,
                fence.owner_instance_id,
                self._millis(authorization.expires_at),
                maximum,
                int(renewing),
                expected,
                uuid4().hex,
                (
                    TransientDescriptor(
                        scope=scope,
                        fence=fence,
                        request_sequence=self._descriptor_source(authorization),
                    ).model_dump_json()
                    if self._descriptor_source is not None
                    else ""
                ),
                policy=policy,
            )
            if result[0] != "ok":
                raise TransientOutputUnavailable(f"temporary activation rejected: {result[0]}")
            self._active[key] = authorization

    def publish(
        self,
        authorization: TransientWriterAuthorization,
        frame: TransientTextFrame,
    ) -> LiveEventCursor:
        with transient_lock(self._lock):
            scope, fence = authorization.scope, authorization.lease_fence
            key = self._keys(scope)[1]
            if self._active.get(key) is not authorization:
                raise TransientOutputUnavailable("writer gate was not activated")
            frame = TransientTextFrame.model_validate_json(frame.wire_bytes())
            authorization.ensure_frame(frame, now=datetime.now(UTC), current_fence=fence)
            result = self._eval(
                PUBLISH,
                scope,
                scope.generation.generation_id,
                str(fence.control_plane_epoch),
                fence.fencing_token,
                fence.owner_instance_id,
                frame.offset,
                frame.wire_bytes(),
                self._max_bytes,
                self._max_rows,
                sha256(frame.wire_bytes()).hexdigest(),
                policy=authorization.capacity_policy,
            )
            if result[0] != "ok":
                raise TransientOutputUnavailable(f"temporary append rejected: {result[0]}")
            return LiveEventCursor(result[1], stream_ref=key)

    def invalidate(self, scope: TransientStreamScope) -> None:
        try:
            active = self._active.get(self._keys(scope)[1])
            if active is None or active.capacity_policy is None:
                raise TransientOutputUnavailable("invalidation has no activated capacity policy")
            result = self._eval(
                INVALIDATE, scope, scope.generation.generation_id, policy=active.capacity_policy
            )
            if result[0] != "ok":
                raise TransientOutputUnavailable(f"temporary invalidation rejected: {result[0]}")
        finally:
            with transient_lock(self._lock):
                self._active.pop(self._keys(scope)[1], None)
        # The exact call gate is retired by Worker; constructing a replacement grants nothing.

    def capture_barrier(self, scope: TransientStreamScope) -> TransientResumeCursor:
        if self._read_authority is None:
            raise TransientOutputUnavailable("fresh read authority is required")
        deadline = min(
            self._millis(self._read_authority(scope)), self._millis(datetime.now(UTC)) + 30_000
        )
        result = self._eval(READ, scope, scope.generation.generation_id, deadline, "barrier")
        if result[0] != "ok":
            raise TransientOutputUnavailable("temporary barrier requires resync")
        offset = int(result[2])
        return TransientResumeCursor(
            scope=scope,
            durable_sequence=0,
            live_cursor=LiveEventCursor(result[1], stream_ref=self._keys(scope)[1]),
            live_offset=None if offset < 0 else offset,
        )

    def read_after(
        self,
        *,
        scope: TransientStreamScope,
        cursor: TransientResumeCursor,
        authorized_until: datetime,
        count: int = 100,
        block_ms: int = 0,
    ) -> TransientOutputBatch:
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError("count must be between 1 and 100")
        if type(block_ms) is not int or not 0 <= block_ms <= 1000:
            raise ValueError("block_ms must be between 0 and 1000")
        key = self._keys(scope)[1]
        empty = TransientResumeCursor(
            scope=scope,
            durable_sequence=cursor.durable_sequence,
            durable_frame_index=cursor.durable_frame_index,
        )
        if cursor.scope != scope or (cursor.live_cursor and cursor.live_cursor.stream_ref != key):
            return TransientOutputBatch(next_cursor=empty, resync_required=True)
        try:
            if self._read_authority is None:
                return TransientOutputBatch(next_cursor=empty, resync_required=True)
            deadline = min(
                self._millis(authorized_until), self._millis(self._read_authority(scope))
            )
            now = self._millis(datetime.now(UTC))
            if now >= deadline:
                return TransientOutputBatch(next_cursor=empty, resync_required=True)
            value = cursor.live_cursor.value if cursor.live_cursor else "0-0"
            offset = cursor.live_offset if cursor.live_offset is not None else -1
            if block_ms:
                self._client.xread({key: value}, count=1, block=min(block_ms, deadline - now))
            result = self._eval(
                READ, scope, scope.generation.generation_id, deadline, value, count, offset
            )
            if result[0] != "ok":
                return TransientOutputBatch(next_cursor=empty, resync_required=True)
            frames: list[TransientTextFrame] = []
            next_cursor = cursor
            for index in range(1, len(result), 2):
                frame = TransientTextFrame.model_validate_json(result[index + 1])
                if frame.generation != scope.generation or frame.offset != offset + 1:
                    raise ValueError("temporary frame scope or offset mismatch")
                offset = frame.offset
                frames.append(frame)
                next_cursor = cursor.model_copy(
                    update={
                        "live_cursor": LiveEventCursor(result[index], stream_ref=key),
                        "live_offset": offset,
                    }
                )
            if self._millis(datetime.now(UTC)) >= deadline:
                return TransientOutputBatch(next_cursor=empty, resync_required=True)
            return TransientOutputBatch(frames=tuple(frames), next_cursor=next_cursor)
        except (RedisError, OSError, TransientOutputUnavailable, ValueError):
            return TransientOutputBatch(next_cursor=empty, resync_required=True)


    def seal_capacity(
        self, scope: TransientStreamScope, policy: TransientCapacityPolicy, *,
        old_keys: tuple[str, ...], old_writers_quiescent: bool, old_ttl_drained: bool,
    ) -> None:
        """Explicit operator cutover; assertions alone do not certify fleet inventory."""
        if old_writers_quiescent is not True or old_ttl_drained is not True:
            raise TransientOutputUnavailable("old provisional writers have not drained")
        if len(old_keys) > 512 or any(
            not key.startswith(self._prefix + ":") or len(key) > 512 for key in old_keys
        ):
            raise ValueError("bounded owned inventory required")
        ledger, due, _ = self._capacity_keys(scope)
        result = self._client.eval(SEAL, 2 + len(old_keys), ledger, due, *old_keys,
                                   policy.epoch, policy.digest)
        if result[0] not in ("ok", b"ok"):
            raise TransientOutputUnavailable("capacity epoch could not be sealed")

    def collect_capacity(
        self, scope: TransientStreamScope, policy: TransientCapacityPolicy, *, count: int = 32,
    ) -> int:
        if type(count) is not int or not 1 <= count <= 32:
            raise ValueError("capacity collection count must be 1..32")
        return self.collect_namespace_capacity(scope.deployment_namespace, policy, count=count)

    def collect_namespace_capacity(
        self, namespace: str, policy: TransientCapacityPolicy, *, count: int = 32,
    ) -> int:
        if type(count) is not int or not 1 <= count <= 32:
            raise ValueError("capacity collection count must be 1..32")
        ledger = transient_deployment_key(namespace, key_prefix=self._prefix)
        parent = current_redis_io_deadline()
        budget = min(2000, int((parent-monotonic())*1000)) if parent is not None else 2000
        if budget <= 0:
            raise TimeoutError("capacity collection deadline expired")
        result = self._client.eval(
            GC, 2, ledger, ledger + ":due", policy.epoch, policy.digest, count, budget
        )
        if result[0] not in ("ok", b"ok"):
            raise TransientOutputUnavailable("capacity collection requires recovery")
        return int(result[1])

    def close(self) -> None:
        self._client.close()
        self._client.connection_pool.disconnect()
