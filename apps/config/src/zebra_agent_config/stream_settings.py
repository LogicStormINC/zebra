"""New-admission switch only; frozen v2 Runs remain readable and writable."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class StreamSettings:
    new_admission_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.new_admission_enabled) is not bool:
            raise ValueError("stream admission flag must be boolean")


def load_stream_settings(values: Mapping[str, str]) -> StreamSettings:
    value = values.get("ZEBRA_STREAM_V2_NEW_ADMISSION_ENABLED", "false").strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("stream admission flag must be true/false or 1/0")
    return StreamSettings(new_admission_enabled=value in {"true", "1"})
