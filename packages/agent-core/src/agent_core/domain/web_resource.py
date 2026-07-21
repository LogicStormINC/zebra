from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass

WEB_RESOURCE_ID_PREFIX = "web_"
# Cropped base32 alphabet (Crockford without I/L/O/U to stay unambiguous).
_RESOURCE_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_RESOURCE_ID_PATTERN = re.compile(r"^web_[0-9a-hjkmnpqrstvwxyz]{20,32}$")


class WebResourceIdError(ValueError):
    """Raised when a web resource id is outside the bounded contract."""


@dataclass(frozen=True)
class WebResourceId:
    """Opaque, validated identifier for a fetched/stored web resource.

    The model only ever sees this string — never an on-disk path. Cursor and
    pagination tokens are derived from it but are independently opaque.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _RESOURCE_ID_PATTERN.match(self.value):
            raise WebResourceIdError("web resource id is outside the bounded contract")

    def __str__(self) -> str:
        return self.value

    @classmethod
    def new(cls) -> WebResourceId:
        """Generate a fresh, time-sortable resource id.

        Layout: ``web_`` + 13 base32-ish chars of millisecond timestamp +
        13 chars of randomness. The timestamp prefix keeps ids sortable on disk
        without leaking anything beyond coarse creation time.
        """
        timestamp_ms = int(time.time() * 1000)
        stamp = _encode_base32(timestamp_ms, length=13)
        randomness = _encode_base32(secrets.randbits(65), length=13)
        return cls(f"{WEB_RESOURCE_ID_PREFIX}{stamp}{randomness}")

    @classmethod
    def parse(cls, value: object) -> WebResourceId:
        if not isinstance(value, str):
            raise WebResourceIdError("web resource id must be a string")
        return cls(value)


def _encode_base32(number: int, *, length: int) -> str:
    base = len(_RESOURCE_ALPHABET)
    characters: list[str] = []
    for _ in range(length):
        characters.append(_RESOURCE_ALPHABET[number % base])
        number //= base
    return "".join(reversed(characters))


# ---------------------------------------------------------------------------
# Read-only views + store port shared by the projection layer (agent-tools)
# and the storage implementation (agent-storage). Keeping these in agent-core
# avoids a tools->storage dependency inversion.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebResourceView:
    """Read-only projection of a stored web resource exposed to tooling."""

    resource_id: str
    final_url: str
    resource_status: str
    clean_chars: int
    title: str | None = None
    canonical_url: str | None = None


@dataclass(frozen=True)
class WebChunkView:
    ordinal: int
    heading_path: str | None
    char_start: int
    char_end: int
    token_count: int
    text: str


@dataclass(frozen=True)
class WebRankedChunkView:
    chunk: WebChunkView
    rank: float


class WebResourceStorePort:
    """Interface the projection/read/find tools depend on. Implementations
    live in agent-storage; the model never sees disk paths, only resource ids."""

    def get(self, resource_id: WebResourceId) -> WebResourceView | None:
        raise NotImplementedError

    def chunks(self, resource_id: WebResourceId) -> tuple[WebChunkView, ...]:
        raise NotImplementedError

    def clean_text(self, resource_id: WebResourceId) -> str:
        raise NotImplementedError

    def search(
        self, resource_id: WebResourceId, query: str, *, top_k: int = 12
    ) -> tuple[WebRankedChunkView, ...]:
        raise NotImplementedError
