from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast
from uuid import UUID

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.live_event_fanout import (
    LiveEventBatch,
    LiveEventCursor,
    LiveEventEnvelope,
)
from redis import Redis
from redis.exceptions import ResponseError

_SCHEMA_VERSION = "1"
_EMPTY_STREAM_CURSOR = "0-0"
_MAX_READ_COUNT = 1_000


class RedisLiveEventError(RuntimeError):
    """Raised when a Redis live-event entry violates the canonical envelope."""


class RedisStreamClient(Protocol):
    def xadd(
        self,
        name: str,
        fields: Mapping[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = False,
    ) -> str | bytes: ...

    def xinfo_stream(self, name: str) -> Mapping[str | bytes, object]: ...

    def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> Sequence[tuple[str | bytes, Sequence[tuple[str | bytes, Mapping[Any, Any]]]]]: ...


class RedisLiveEventFanout:
    """Redis Streams implementation of the ephemeral live-event Port.

    The caller captures a stream barrier before replaying PostgreSQL. Reading
    after that barrier and filtering by the durable sequence closes the replay
    to live-tail handoff without making Redis authoritative.
    """

    def __init__(
        self,
        client: RedisStreamClient,
        *,
        max_stream_length: int = 1_000,
        key_prefix: str = "zebra:live:v1",
    ) -> None:
        if max_stream_length < 1:
            raise ValueError("max_stream_length must be positive")
        if not key_prefix or key_prefix != key_prefix.strip() or " " in key_prefix:
            raise ValueError("key_prefix must be non-blank and contain no spaces")
        self._client = client
        self._max_stream_length = max_stream_length
        self._key_prefix = key_prefix

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        max_stream_length: int = 1_000,
        key_prefix: str = "zebra:live:v1",
    ) -> RedisLiveEventFanout:
        if not url or url != url.strip():
            raise ValueError("Redis URL must be non-blank and trimmed")
        client = cast(RedisStreamClient, Redis.from_url(url, decode_responses=True))
        return cls(client, max_stream_length=max_stream_length, key_prefix=key_prefix)

    def capture_barrier(
        self,
        *,
        deployment_namespace: str,
        session_id: SessionId,
    ) -> LiveEventCursor:
        key = self._stream_key(deployment_namespace, session_id)
        try:
            info = self._client.xinfo_stream(key)
        except ResponseError as exc:
            if "no such key" in str(exc).lower():
                return LiveEventCursor(_EMPTY_STREAM_CURSOR, stream_ref=key)
            raise
        return self._cursor(info.get("last-generated-id", info.get(b"last-generated-id")), key)

    def publish(
        self,
        *,
        deployment_namespace: str,
        event: SessionEvent,
    ) -> LiveEventCursor:
        namespace = self._namespace(deployment_namespace)
        key = self._stream_key(namespace, event.session_id)
        event_json = json.dumps(
            event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        cursor = self._client.xadd(
            key,
            {
                "schema_version": _SCHEMA_VERSION,
                "namespace": namespace,
                "session_id": str(event.session_id),
                "event_id": str(event.event_id),
                "event_sequence": str(event.sequence),
                "event_type": event.event_type.value,
                "event": event_json,
            },
            maxlen=self._max_stream_length,
            approximate=False,
        )
        return self._redis_cursor(cursor, key)

    def read_after(
        self,
        *,
        deployment_namespace: str,
        session_id: SessionId,
        barrier: LiveEventCursor,
        durable_sequence: int,
        count: int = 100,
        block_ms: int = 0,
    ) -> LiveEventBatch:
        namespace = self._namespace(deployment_namespace)
        expected_session = self._session_id(session_id)
        if durable_sequence < -1:
            raise ValueError("durable_sequence must be >= -1")
        if count < 1 or count > _MAX_READ_COUNT:
            raise ValueError("count must be between 1 and 1000")
        if block_ms < 0 or block_ms > 60_000:
            raise ValueError("block_ms must be between 0 and 60000")
        key = self._stream_key(namespace, expected_session)
        if barrier.stream_ref is not None and barrier.stream_ref != key:
            raise RedisLiveEventError("live-event barrier does not match namespace or session")
        response = self._client.xread(
            {key: self._redis_cursor(barrier.value).value},
            count=count,
            block=block_ms or None,
        )
        entries: list[LiveEventEnvelope] = []
        seen_event_ids: set[str] = set()
        next_cursor = barrier
        for stream_name, stream_entries in response or ():
            if self._text(stream_name) != key:
                raise RedisLiveEventError("Redis returned an unexpected live-event stream")
            for cursor, raw_fields in stream_entries:
                envelope = self._decode_entry(
                    namespace=namespace,
                    session_id=expected_session,
                    cursor=cursor,
                    fields=raw_fields,
                )
                next_cursor = envelope.cursor
                if envelope.event.sequence <= durable_sequence:
                    continue
                event_id = str(envelope.event.event_id)
                if event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event_id)
                entries.append(envelope)
        return LiveEventBatch(events=tuple(entries), next_cursor=next_cursor)

    def _decode_entry(
        self,
        *,
        namespace: str,
        session_id: UUID,
        cursor: str | bytes,
        fields: Mapping[Any, Any],
    ) -> LiveEventEnvelope:
        try:
            normalized = {self._text(key): self._text(value) for key, value in fields.items()}
        except (UnicodeDecodeError, TypeError) as exc:
            raise RedisLiveEventError("Redis live-event fields are not valid text") from exc
        expected_fields = {
            "schema_version",
            "namespace",
            "session_id",
            "event_id",
            "event_sequence",
            "event_type",
            "event",
        }
        if set(normalized) != expected_fields or normalized["schema_version"] != _SCHEMA_VERSION:
            raise RedisLiveEventError("Redis live-event schema is invalid")
        if normalized["namespace"] != namespace or normalized["session_id"] != str(session_id):
            raise RedisLiveEventError("Redis live-event namespace or session does not match")
        try:
            event = SessionEvent.model_validate(json.loads(normalized["event"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RedisLiveEventError("Redis live-event payload is invalid") from exc
        if (
            str(event.event_id) != normalized["event_id"]
            or str(event.session_id) != normalized["session_id"]
            or str(event.sequence) != normalized["event_sequence"]
            or event.event_type.value != normalized["event_type"]
        ):
            raise RedisLiveEventError("Redis live-event metadata does not match payload")
        return LiveEventEnvelope(
            deployment_namespace=namespace,
            event=event,
            cursor=self._redis_cursor(cursor, self._stream_key(namespace, session_id)),
        )

    def _stream_key(self, namespace: str, session_id: SessionId | UUID) -> str:
        namespace = self._namespace(namespace)
        encoded_namespace = namespace.encode("utf-8").hex()
        return f"{self._key_prefix}:{encoded_namespace}:{self._session_id(session_id)}"

    @staticmethod
    def _namespace(value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip() or len(value) > 255:
            raise ValueError("deployment_namespace must be non-blank, trimmed and <= 255 chars")
        return value

    @staticmethod
    def _session_id(value: SessionId | UUID) -> UUID:
        try:
            return UUID(str(value))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("session_id must be a UUID") from exc

    @classmethod
    def _redis_cursor(
        cls, value: str | bytes | object, stream_ref: str | None = None
    ) -> LiveEventCursor:
        cursor = cls._text(value)
        if "-" not in cursor or cursor.startswith("-") or cursor.endswith("-"):
            raise RedisLiveEventError("Redis returned an invalid stream cursor")
        return LiveEventCursor(cursor, stream_ref=stream_ref)

    @staticmethod
    def _cursor(value: object, stream_ref: str) -> LiveEventCursor:
        if value is None:
            return LiveEventCursor(_EMPTY_STREAM_CURSOR, stream_ref=stream_ref)
        return RedisLiveEventFanout._redis_cursor(value, stream_ref)

    @staticmethod
    def _text(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, str):
            return value
        return str(value)
