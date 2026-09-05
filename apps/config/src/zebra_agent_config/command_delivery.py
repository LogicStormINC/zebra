"""Explicit default-off broker process settings; no optional transport imports."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class CommandDeliverySettings:
    publish_enabled: bool = False
    consume_enabled: bool = False
    scan_fallback_enabled: bool = True
    scoped_rollout_enabled: bool = False
    relay_url: str | None = field(default=None, repr=False)
    consumer_url: str | None = field(default=None, repr=False)
    shadow_consumer_url: str | None = field(default=None, repr=False)
    execution_slots: int = 4
    batch_size: int = 16
    tick_seconds: float = 0.25
    transport_timeout: float = 10.0

    def __post_init__(self) -> None:
        if any(
            type(v) is not bool
            for v in (
                self.publish_enabled,
                self.consume_enabled,
                self.scan_fallback_enabled,
                self.scoped_rollout_enabled,
            )
        ):
            raise ValueError("command delivery flags must be boolean")
        if not self.scan_fallback_enabled and not (self.consume_enabled and self.publish_enabled):
            raise ValueError("command delivery requires fallback or both broker execution paths")
        if self.scoped_rollout_enabled and not (
            self.publish_enabled and self.consume_enabled and self.scan_fallback_enabled
        ):
            raise ValueError("scoped rollout requires broker and fallback execution paths")
        if (
            type(self.execution_slots) is not int
            or not 1 <= self.execution_slots <= 32
            or type(self.batch_size) is not int
            or not 1 <= self.batch_size <= 100
        ):
            raise ValueError("command delivery concurrency is outside bounds")
        for value, upper in ((self.tick_seconds, 30), (self.transport_timeout, 20)):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0.05 <= value <= upper
            ):
                raise ValueError("command delivery time bound is invalid")
        if self.publish_enabled or self.consume_enabled:
            self._validate_url(self.relay_url)
        if self.consume_enabled:
            self._validate_url(self.consumer_url)
        if self.scoped_rollout_enabled:
            self._validate_url(self.shadow_consumer_url)
            if self._principal(self.shadow_consumer_url) == self._principal(self.consumer_url):
                raise ValueError("shadow consumer requires separate credentials")

    @staticmethod
    def _principal(value: str | None) -> str:
        return unquote(urlsplit(value or "").username or "guest")

    @staticmethod
    def _validate_url(value: str | None) -> None:
        try:
            parsed = urlsplit(value or "")
            valid = parsed.scheme in {"amqp", "amqps"} and parsed.hostname and parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("command delivery requires an explicit Rabbit endpoint")


def load_command_delivery(values: Mapping[str, str]) -> CommandDeliverySettings:
    def flag(key: str, default: bool) -> bool:
        value = values.get(key, str(default)).strip().lower()
        if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError("invalid command delivery flag")
        return value in {"true", "1", "yes", "on"}

    try:
        return CommandDeliverySettings(
            publish_enabled=flag("ZEBRA_RABBIT_PUBLISH_ENABLED", False),
            consume_enabled=flag("ZEBRA_RABBIT_CONSUME_ENABLED", False),
            scan_fallback_enabled=flag("ZEBRA_COMMAND_SCAN_FALLBACK_ENABLED", True),
            scoped_rollout_enabled=flag("ZEBRA_COMMAND_SCOPED_ROLLOUT_ENABLED", False),
            relay_url=values.get("ZEBRA_RABBIT_RELAY_URL"),
            consumer_url=values.get("ZEBRA_RABBIT_CONSUMER_URL"),
            shadow_consumer_url=values.get("ZEBRA_RABBIT_SHADOW_CONSUMER_URL"),
            execution_slots=int(values.get("ZEBRA_COMMAND_EXECUTION_SLOTS", "4")),
            batch_size=int(values.get("ZEBRA_COMMAND_BATCH_SIZE", "16")),
            tick_seconds=float(values.get("ZEBRA_COMMAND_TICK_SECONDS", ".25")),
            transport_timeout=float(values.get("ZEBRA_RABBIT_TIMEOUT_SECONDS", "10")),
        )
    except (ValueError, TypeError):
        raise ValueError("invalid command delivery configuration") from None
