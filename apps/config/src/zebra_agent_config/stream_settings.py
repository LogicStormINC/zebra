"""New-admission switch only; frozen v2 Runs remain readable and writable."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StreamSettings:
    new_admission_enabled: bool = False
    cursor_signing_key: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.new_admission_enabled) is not bool:
            raise ValueError("stream admission flag must be boolean")
        if self.cursor_signing_key is not None and (
            not isinstance(self.cursor_signing_key, bytes) or len(self.cursor_signing_key) < 32
        ):
            raise ValueError("shared stream cursor signing key requires at least 32 bytes")


def load_stream_settings(values: Mapping[str, str]) -> StreamSettings:
    value = values.get("ZEBRA_STREAM_V2_NEW_ADMISSION_ENABLED", "false").strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("stream admission flag must be true/false or 1/0")
    key = values.get("ZEBRA_STREAM_V2_CURSOR_SIGNING_KEY", "")
    return StreamSettings(
        new_admission_enabled=value in {"true", "1"},
        cursor_signing_key=key.encode() if key else None,
    )
