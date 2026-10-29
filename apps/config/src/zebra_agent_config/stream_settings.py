"""New-admission switch only; frozen v2 Runs remain readable and writable."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_core.domain.stream_admission import TransientCapacityPolicy


@dataclass(frozen=True)
class StreamSettings:
    new_admission_enabled: bool = False
    capacity_policy: TransientCapacityPolicy | None = None
    cursor_signing_key: bytes | None = field(default=None, repr=False)
    agui_profiles_enabled: bool = False
    agui_native_interaction_enabled: bool = False

    def __post_init__(self) -> None:
        if self.capacity_policy is not None and not isinstance(
            self.capacity_policy, TransientCapacityPolicy
        ):
            raise ValueError("capacity policy must be a validated immutable policy")
        if type(self.agui_native_interaction_enabled) is not bool:
            raise ValueError("AG-UI native interaction flag must be boolean")
        if type(self.agui_profiles_enabled) is not bool:
            raise ValueError("AG-UI profile flag must be boolean")
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
    agui = values.get("ZEBRA_AGUI_STANDARD_PROFILES_ENABLED", "false").strip().lower()
    if agui not in {"true", "false", "1", "0"}:
        raise ValueError("AG-UI profile flag must be true/false or 1/0")
    interactions = values.get("ZEBRA_AGUI_NATIVE_INTERACTION_ENABLED", "false").strip().lower()
    if interactions not in {"true", "false", "1", "0"}:
        raise ValueError("AG-UI native interaction flag must be true/false or 1/0")
    key = values.get("ZEBRA_STREAM_V2_CURSOR_SIGNING_KEY", "")
    return StreamSettings(
        agui_profiles_enabled=agui in {"true", "1"},
        agui_native_interaction_enabled=interactions in {"true", "1"},
        new_admission_enabled=value in {"true", "1"},
        capacity_policy=(
            TransientCapacityPolicy.model_validate_json(values["ZEBRA_STREAM_CAPACITY_POLICY"])
            if values.get("ZEBRA_STREAM_CAPACITY_POLICY")
            else None
        ),
        cursor_signing_key=key.encode() if key else None,
    )
