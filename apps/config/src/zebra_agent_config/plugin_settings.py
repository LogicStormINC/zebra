"""Default-off Cloud plugin packages supplied through a read-only operator mount."""

import re
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PluginSettings:
    enabled: bool = False
    bundle_root: str = ""
    allowed_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None for digest in self.allowed_digests
        ):
            raise ValueError("plugin allowlist requires complete sha256 digests")


def load_plugins(values: Mapping[str, str]) -> PluginSettings:
    digests = values.get("ZEBRA_CLOUD_PLUGIN_ALLOWED_DIGESTS", "")
    return PluginSettings(
        enabled=values.get("ZEBRA_CLOUD_PLUGINS_ENABLED", "false").strip().lower()
        in {"true", "1", "yes", "on"},
        bundle_root=values.get("ZEBRA_CLOUD_PLUGIN_BUNDLE_ROOT", "").strip(),
        allowed_digests=tuple(digest.strip() for digest in digests.split(",") if digest.strip()),
    )
