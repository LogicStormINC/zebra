"""Bounded, authenticated transport coordinates; fresh read authority stays separate."""

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass

MAX_STREAM_CURSOR_LENGTH = 4096
_DOMAIN = b"zebra:stream:v2:cursor\x00"
_PROFILE_DOMAIN = b"zebra:stream:v2:agui-profile-cursor\x00"


@dataclass(frozen=True, slots=True)
class StreamV2Cursor:
    scope: str
    durable: str | None = None
    generation: str | None = None
    live_id: str | None = None
    live_offset: int | None = None
    chunk_index: int | None = None
    live_chunk_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, str) or not self.scope or len(self.scope) > 128:
            raise ValueError("invalid stream scope digest")
        for value in (self.durable, self.generation, self.live_id):
            if value is not None and (
                not isinstance(value, str)
                or not value
                or len(value) > 2048
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError("invalid stream coordinate")
        if self.live_offset is not None and (
            type(self.live_offset) is not int or not 0 <= self.live_offset < 8192
        ):
            raise ValueError("invalid live offset")
        if self.live_chunk_index is not None and (
            type(self.live_chunk_index) is not int
            or not 0 <= self.live_chunk_index < 4096
            or self.generation is None
        ):
            raise ValueError("invalid partial live chunk index")
        if self.chunk_index is not None and (
            type(self.chunk_index) is not int or not 0 <= self.chunk_index < 4096
        ):
            raise ValueError("invalid wire chunk index")
        if (self.live_id is None) != (self.live_offset is None):
            raise ValueError("live coordinates must be paired")
        if self.live_id is not None and self.generation is None:
            raise ValueError("live coordinates require a generation")


class StreamV2CursorCodec:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("stream cursor key requires at least 32 bytes")
        self._key = key

    def encode(self, cursor: StreamV2Cursor) -> str:
        body = json.dumps(
            [
                2,
                cursor.scope,
                cursor.durable,
                cursor.generation,
                cursor.live_id,
                cursor.live_offset,
                cursor.chunk_index,
                cursor.live_chunk_index,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode()
        profiled = cursor.scope.startswith("agui:")
        domain = _PROFILE_DOMAIN if profiled else _DOMAIN
        signature = hmac.digest(self._key, domain + body, hashlib.sha256)
        token = ("v2p." if profiled else "v2.") + base64.urlsafe_b64encode(body + signature).rstrip(
            b"="
        ).decode()
        if len(token) > MAX_STREAM_CURSOR_LENGTH:
            raise ValueError("stream cursor exceeds its wire budget")
        return token

    def decode(self, token: str, *, scope: str) -> StreamV2Cursor:
        if not token.startswith(("v2.", "v2p.")) or len(token) > MAX_STREAM_CURSOR_LENGTH:
            raise ValueError("invalid stream cursor")
        try:
            profiled = token.startswith("v2p.")
            encoded = token[4:] if profiled else token[3:]
            raw = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
            body, supplied = raw[:-32], raw[-32:]
            domain = _PROFILE_DOMAIN if profiled else _DOMAIN
            expected = hmac.digest(self._key, domain + body, hashlib.sha256)
            if len(supplied) != 32 or not hmac.compare_digest(expected, supplied):
                raise ValueError("invalid stream cursor signature")
            values = json.loads(body)
            if (
                not isinstance(values, list)
                or len(values) != 8
                or type(values[0]) is not int
                or values[0] != 2
            ):
                raise ValueError("invalid stream cursor version")
            cursor = StreamV2Cursor(*values[1:])
            if cursor.scope != scope or self.encode(cursor) != token:
                raise ValueError("stream cursor scope or encoding mismatch")
            return cursor
        except (binascii.Error, UnicodeError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("malformed stream cursor") from exc
