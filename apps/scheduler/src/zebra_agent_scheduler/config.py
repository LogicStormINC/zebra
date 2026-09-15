"""Fail-fast environment contract for the Schedule materializer."""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass

from agent_integrations import ScheduleGrantExchangeSettings
from agent_security import HostGrantVerificationConfig, JwtAlgorithm


@dataclass(frozen=True)
class SchedulerSettings:
    claimant: str
    poll_seconds: float
    batch_size: int
    claim_ttl_seconds: int
    max_attempts: int
    grant_exchange: ScheduleGrantExchangeSettings

    def __post_init__(self) -> None:
        if not self.claimant or len(self.claimant) > 256:
            raise ValueError("scheduler claimant must be non-blank and bounded")


def load_scheduler_settings(env: Mapping[str, str] | None = None) -> SchedulerSettings:
    values = os.environ if env is None else env
    issuer = _required(values, "ZEBRA_SCHEDULER_GRANT_ISSUER")
    verification = HostGrantVerificationConfig(
        issuer=issuer,
        audience=_required(values, "ZEBRA_SCHEDULER_GRANT_AUDIENCE"),
        jwks_uri=_required(values, "ZEBRA_SCHEDULER_GRANT_JWKS_URI"),
        allowed_origins=_csv(values, "ZEBRA_SCHEDULER_ALLOWED_ORIGINS"),
        algorithms=frozenset({JwtAlgorithm.RS256}),
    )
    return SchedulerSettings(
        claimant=(values.get("ZEBRA_SCHEDULER_ID") or f"scheduler:{socket.gethostname()}").strip(),
        poll_seconds=_float(values, "ZEBRA_SCHEDULER_POLL_SECONDS", 1.0, 0.05, 60.0),
        batch_size=_integer(values, "ZEBRA_SCHEDULER_BATCH_SIZE", 20, 1, 200),
        claim_ttl_seconds=_integer(values, "ZEBRA_SCHEDULER_CLAIM_TTL_SECONDS", 60, 1, 3600),
        max_attempts=_integer(values, "ZEBRA_SCHEDULER_MAX_ATTEMPTS", 3, 1, 20),
        grant_exchange=ScheduleGrantExchangeSettings(
            exchange_url=_required(values, "ZEBRA_SCHEDULER_GRANT_EXCHANGE_URL"),
            workload_identity=_required(values, "ZEBRA_SCHEDULER_WORKLOAD_IDENTITY"),
            workload_shared_secret=_required(values, "ZEBRA_SCHEDULER_WORKLOAD_SHARED_SECRET"),
            verification=verification,
            timeout_seconds=_float(values, "ZEBRA_SCHEDULER_GRANT_TIMEOUT_SECONDS", 5.0, 0.1, 30.0),
        ),
    )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise ValueError(f"scheduler requires {name}")
    return value


def _csv(values: Mapping[str, str], name: str) -> tuple[str, ...]:
    result = tuple(item.strip() for item in _required(values, name).split(",") if item.strip())
    if not result:
        raise ValueError(f"scheduler requires {name}")
    return result


def _integer(values: Mapping[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        result = int(values.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def _float(
    values: Mapping[str, str], name: str, default: float, minimum: float, maximum: float
) -> float:
    try:
        result = float(values.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result
