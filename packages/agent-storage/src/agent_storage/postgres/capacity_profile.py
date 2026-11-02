"""Operator-declared peak process inventory; never inferred from one pool."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

COMPONENTS = frozenset({"api", "worker", "executor", "cleanup", "scheduler"})


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate database budget key")
        result[key] = value
    return result


@dataclass(frozen=True)
class CapacityProfile:
    pool: int
    normal: int
    read: int
    control: int
    probe: int
    max_connections: int
    server_reserved: int
    external: int
    execution_slots: int
    fleet: Mapping[str, int]

    @classmethod
    def parse(cls, value: str) -> "CapacityProfile":
        if len(value) > 8192:
            raise ValueError("database budget profile is too large")
        try:
            data = json.loads(value, object_pairs_hook=_unique)
            if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
                raise ValueError("database budget requires the complete inventory")
            for key in ("pool", "normal", "read", "control", "probe", "execution_slots"):
                if type(data[key]) is not int or not 1 <= data[key] <= 32:
                    raise ValueError("database budget limit outside bounds")
            for key in ("max_connections", "server_reserved", "external"):
                if type(data[key]) is not int or not 0 <= data[key] <= 262143:
                    raise ValueError("invalid database server budget")
            if data["external"] < 1:
                raise ValueError("database budget must reserve migration/operator connections")
            fleet = data["fleet"]
            if not isinstance(fleet, dict) or set(fleet) != COMPONENTS:
                raise ValueError("database budget requires all process components")
            if any(type(v) is not int or not 0 <= v <= 32768 for v in fleet.values()):
                raise ValueError("invalid peak process count")
            if fleet["api"] < 1 or fleet["worker"] < 1:
                raise ValueError("database budget requires API and Worker peak counts")
            if fleet["executor"] < fleet["worker"] * data["execution_slots"]:
                raise ValueError("database budget omits peak private executors")
            data["fleet"] = MappingProxyType(fleet)
            profile = cls(**data)
            if (profile.fleet_connections + profile.server_reserved + profile.external
                > profile.max_connections):
                raise ValueError("database fleet exceeds server connection budget")
            return profile
        except (TypeError, KeyError, RecursionError) as exc:
            raise ValueError("invalid database budget profile") from exc

    @property
    def fleet_connections(self) -> int:
        # Counts are PEAKS including deployment surge, not steady replica targets.
        per_process = self.pool + self.normal + self.read + self.control + self.probe
        return sum(self.fleet.values()) * per_process

    def require_server(self, row: dict[str, Any]) -> None:
        if (row["maximum"] != self.max_connections
            or row["reserved"] != self.server_reserved or row["superuser"] is not False):
            raise ValueError("database server capacity or application role differs from profile")
