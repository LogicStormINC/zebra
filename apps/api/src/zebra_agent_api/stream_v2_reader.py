"""Merge bounded canonical replay and scoped visual drafts without per-frame SQL."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic

import psycopg
from agent_core.ports.live_event_fanout import LiveEventCursor
from agent_core.ports.transient_output import TransientResumeCursor, TransientStreamScope
from agent_integrations.redis_live_fanout_async import AsyncRedisNotifications
from agent_integrations.redis_transient_discovery import TransientDescriptor, discover
from agent_integrations.redis_transient_output import RedisTransientOutput

from zebra_agent_api.ag_ui_checkpoint_tail import _read_until, observation_problem
from zebra_agent_api.stream_v2_authority import V2ReadAuthority, V2ReadBinding
from zebra_agent_api.stream_v2_cursor import StreamV2Cursor, StreamV2CursorCodec
from zebra_agent_api.stream_v2_wire import (
    canonical_call,
    canonical_wire,
    draft_wire,
    parse_record,
    stream_notice,
)


@dataclass(frozen=True, slots=True)
class V2StreamContext:
    binding: V2ReadBinding
    kind: str
    cursor: StreamV2Cursor
    full_recovery: bool
    session_id: str | None = None


class StreamV2Reader:
    def __init__(
        self,
        authority: V2ReadAuthority,
        *,
        url: str,
        key: bytes,
        live_prefix: str,
    ) -> None:
        self.authority, self.codec, self.live_prefix = (
            authority,
            StreamV2CursorCodec(key),
            live_prefix,
        )
        self.notifications = AsyncRedisNotifications(url, key_prefix=live_prefix)
        self.port = RedisTransientOutput.from_url(
            url, resolve_authorization=lambda _: None, read_timeout=0.25
        )

    def context(
        self,
        binding: V2ReadBinding,
        *,
        kind: str,
        token: str | None,
        full_recovery: bool,
        session_id: str | None = None,
    ) -> V2StreamContext:
        if kind == "session" and session_id is None:
            assert binding.authority.allowed_session_ids is not None
            session_id = binding.authority.allowed_session_ids[0]
        identity = (binding.lane, kind) + ((session_id,) if kind == "session" else ())
        digest = sha256(
            json.dumps(
                identity,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        cursor = (
            self.codec.decode(token, scope=digest)
            if token is not None and not full_recovery
            else StreamV2Cursor(digest)
        )
        return V2StreamContext(binding, kind, cursor, full_recovery or token is None, session_id)

    async def close(self) -> None:
        await self.notifications.close()
        await asyncio.to_thread(self.port._client.close)

    def _read_port(self, scope: TransientStreamScope, expiry: datetime) -> RedisTransientOutput:
        def authority(requested: TransientStreamScope) -> datetime:
            return expiry if requested == scope else datetime.min.replace(tzinfo=UTC)

        return RedisTransientOutput(
            self.port._client,
            resolve_authorization=lambda _: None,
            read_authority=authority,
            key_prefix=self.port._prefix,
        )

    async def tail(
        self,
        context: V2StreamContext,
        durable: AsyncIterator[str],
        *,
        deadline: float,
        disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[str]:
        bound, cursor = context.binding, context.cursor
        assert bound.host.expires_at is not None
        deadline = min(
            deadline,
            monotonic() + max(0, (bound.host.expires_at - datetime.now(UTC)).total_seconds()),
        )
        assert bound.authority.allowed_session_ids is not None
        segment = context.session_id or bound.authority.allowed_session_ids[0]
        provisional = context.kind != "session" or segment == bound.authority.allowed_session_ids[0]
        canonical_key = self.notifications.key(bound.namespace, segment)
        checkpoint_key = self.notifications.key(bound.namespace, bound.task_id, checkpoint=True)
        control_key = bound.lane + ":authority:control"
        # ponytail: one startup budget; Redis loss must not consume the canonical Grant.
        startup_deadline = min(deadline, monotonic() + 0.25)
        unavailable = False
        positions: dict[str, str] = {}
        for key in (canonical_key, checkpoint_key) + ((control_key,) if provisional else ()):
            try:
                async with asyncio.timeout(max(0, startup_deadline - monotonic())):
                    positions[key] = await self.notifications.barrier(key)
            except Exception:
                positions[key] = "0-0"  # Durable replay still owns canonical recovery.
                unavailable = True
        descriptor: TransientDescriptor | None = None
        rejected: TransientDescriptor | None = None
        rejected_until = 0.0
        expiry = datetime.min.replace(tzinfo=UTC)
        live: TransientResumeCursor | None = None
        captured: TransientResumeCursor | None = None
        closed = False
        try:
            initial = (
                await _read_until(startup_deadline, discover, self.port._client, bound.lane)
                if provisional
                else None
            )
        except Exception:
            initial = None
            unavailable = True
        if initial:
            try:
                descriptor = initial[0]
                # XINFO is metadata only: no provisional body read authority before PG proof.
                live_key = f"{bound.lane}:{descriptor.scope.generation.generation_id}:frames"
                async with asyncio.timeout(max(0, startup_deadline - monotonic())):
                    live_id = await self.notifications.barrier(live_key)
                barrier = TransientResumeCursor(
                    scope=descriptor.scope,
                    durable_sequence=0,
                    live_cursor=LiveEventCursor(live_id, stream_ref=live_key),
                )
                assert barrier.live_cursor is not None
                positions[live_key] = live_id
                captured = barrier
            except Exception:
                unavailable = True
                descriptor, captured = None, None
        # Frame, control and checkpoint barriers all precede canonical replay.
        pending = asyncio.create_task(anext(durable, None))
        wake: asyncio.Task[dict[str, str]] | None = None
        dirty = False
        recovered = not context.full_recovery
        resume_chunk = context.cursor.chunk_index
        resume_live = context.cursor.live_chunk_index
        try:
            if monotonic() >= deadline:
                return
            if unavailable:
                cursor = replace(
                    cursor, generation=None, live_id=None, live_offset=None, live_chunk_index=None
                )
                resume_live = None
                yield stream_notice("zebra.stream.reset", {"reason": "provisional_unavailable"})
            if context.full_recovery:
                yield stream_notice("zebra.stream.recovery_start", {})
            while monotonic() < deadline:
                if await disconnected():
                    return
                if pending.done():
                    try:
                        record = pending.result()
                    except (TimeoutError, psycopg.OperationalError):
                        if monotonic() >= deadline or await disconnected():
                            return
                        yield stream_notice(
                            "zebra.stream.reset", {"reason": "canonical_unavailable"}
                        )
                        if monotonic() >= deadline or await disconnected():
                            return
                        yield observation_problem("observation_unavailable", retryable=True)
                        return
                    if record is None:
                        yield stream_notice("zebra.stream.reset", {"reason": "canonical_closed"})
                        return
                    source_id, event = parse_record(record)
                    if source_id:
                        cursor = replace(cursor, durable=source_id, chunk_index=None)
                    if event.get("name") == "zebra.stream.recovery_complete":
                        recovered = True
                    call = canonical_call(event)
                    if descriptor is not None and call == descriptor.scope.generation.model_call_id:
                        closed = True
                    for ordinal, wire in canonical_wire(record, event):
                        if (
                            resume_chunk is not None
                            and source_id == context.cursor.durable
                            and ordinal is not None
                            and ordinal <= resume_chunk
                        ):
                            continue
                        if resume_chunk is not None and source_id == context.cursor.durable:
                            resume_chunk = None
                        cursor = replace(cursor, chunk_index=ordinal)
                        if monotonic() >= deadline:
                            return
                        yield self._signed(wire, cursor)
                    pending = asyncio.create_task(anext(durable, None))
                    continue
                if not recovered:
                    await asyncio.wait({pending}, timeout=min(1, max(0, deadline - monotonic())))
                    continue
                if wake is not None and wake.done():
                    try:
                        changed = wake.result()
                        dirty = any(
                            changed.get(key) != positions[key]
                            for key in (canonical_key, checkpoint_key)
                        )
                        positions = changed
                    except Exception:
                        dirty = True
                        live, resume_live = None, None
                        cursor = replace(
                            cursor,
                            generation=None,
                            live_id=None,
                            live_offset=None,
                            live_chunk_index=None,
                        )
                        yield stream_notice(
                            "zebra.stream.reset", {"reason": "notifications_unavailable"}
                        )
                        await asyncio.sleep(min(1, max(0, deadline - monotonic())))
                    wake = None
                try:
                    located = (
                        await _read_until(deadline, discover, self.port._client, bound.lane)
                        if provisional
                        else None
                    )
                    candidate = located[0] if located else None
                    if candidate == rejected and monotonic() < rejected_until and not dirty:
                        candidate = None
                    if candidate != descriptor:
                        resume_live = None
                        cursor = replace(
                            cursor,
                            generation=None,
                            live_id=None,
                            live_offset=None,
                            live_chunk_index=None,
                        )
                        yield stream_notice("zebra.stream.reset", {"reason": "generation_changed"})
                        for key in list(positions):
                            if key not in {canonical_key, checkpoint_key, control_key}:
                                del positions[key]
                        descriptor, live, captured, dirty = candidate, None, None, True
                        closed = False
                    if descriptor is not None and not closed:
                        scope = descriptor.scope
                        if dirty or datetime.now(UTC) >= expiry:
                            expiry = await _read_until(
                                deadline, self.authority.qualify, bound, descriptor
                            )
                            if (
                                await _read_until(deadline, discover, self.port._client, bound.lane)
                                != located
                            ):
                                raise ValueError("generation changed during qualification")
                            dirty = False
                        port = self._read_port(scope, expiry)
                        if live is None:
                            if captured is not None:
                                barrier = captured
                            else:
                                barrier = await _read_until(deadline, port.capture_barrier, scope)
                            assert (
                                barrier.live_cursor is not None
                                and barrier.live_cursor.stream_ref is not None
                            )
                            positions[barrier.live_cursor.stream_ref] = barrier.live_cursor.value
                            live = TransientResumeCursor(scope=scope, durable_sequence=0)
                            if (
                                not context.full_recovery
                                and cursor.generation == scope.generation.generation_id
                                and cursor.live_offset is not None
                            ):
                                assert cursor.live_id is not None
                                live = live.model_copy(
                                    update={
                                        "live_cursor": LiveEventCursor(
                                            cursor.live_id,
                                            stream_ref=barrier.live_cursor.stream_ref,
                                        ),
                                        "live_offset": cursor.live_offset,
                                    }
                                )
                        batch = await _read_until(
                            deadline,
                            port.read_after,
                            scope=scope,
                            cursor=live,
                            authorized_until=expiry,
                            count=1,
                        )
                        if batch.resync_required:
                            raise ValueError("temporary output requires durable recovery")
                        previous_live = live
                        live = batch.next_cursor
                        for frame in batch.frames:
                            assert live.live_cursor is not None
                            for ordinal, wire in draft_wire(frame):
                                if (
                                    resume_live is not None
                                    and cursor.generation == frame.generation_id
                                    and ordinal is not None
                                    and ordinal <= resume_live
                                ):
                                    continue
                                resume_live = None
                                previous_id = (
                                    previous_live.live_cursor.value
                                    if previous_live.live_cursor
                                    else None
                                )
                                cursor = replace(
                                    cursor,
                                    generation=frame.generation_id,
                                    live_id=previous_id
                                    if ordinal is not None
                                    else live.live_cursor.value,
                                    live_offset=previous_live.live_offset
                                    if ordinal is not None
                                    else frame.offset,
                                    live_chunk_index=ordinal,
                                )
                                if monotonic() >= deadline:
                                    return
                                yield self._signed(wire, cursor)
                        if batch.frames:
                            continue
                except Exception:
                    rejected, rejected_until = descriptor, monotonic() + 30
                    descriptor = None
                    live = None
                    expiry = datetime.min.replace(tzinfo=UTC)
                    dirty = False
                    resume_live = None
                    cursor = replace(
                        cursor,
                        generation=None,
                        live_id=None,
                        live_offset=None,
                        live_chunk_index=None,
                    )
                    yield stream_notice("zebra.stream.reset", {"reason": "provisional_unavailable"})
                if wake is None:
                    wake = asyncio.create_task(
                        self.notifications.wait(
                            positions, block_ms=max(1, int(min(1, deadline - monotonic()) * 1000))
                        )
                    )
                await asyncio.wait(
                    {pending, wake},
                    timeout=min(1, max(0, deadline - monotonic())),
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            pending.cancel()
            if wake is not None:
                wake.cancel()
            await asyncio.gather(pending, *([wake] if wake else []), return_exceptions=True)
            await durable.aclose()  # type: ignore[attr-defined]

    def _signed(self, record: str, cursor: StreamV2Cursor) -> str:
        if record.startswith(":"):
            return record
        encoded = (
            f"id: {self.codec.encode(cursor)}\n"
            + "\n".join(
                line for line in record.rstrip("\n").split("\n") if not line.startswith("id:")
            )
            + "\n\n"
        )
        if len(encoded.encode()) > 16_384:
            raise ValueError("signed stream frame exceeds wire budget")
        return encoded
