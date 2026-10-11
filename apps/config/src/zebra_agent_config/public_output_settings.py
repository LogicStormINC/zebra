"""Central, validated defaults for public communication; frozen per durable Turn."""

from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from agent_core.harness.public_output import PublicOutputPolicy as PublicOutputPolicy


def load_public_output_policy(values: Mapping[str, str]) -> PublicOutputPolicy:
    defaults = PublicOutputPolicy()
    settings: dict[str, Any] = {}
    for field in fields(defaults):
        raw = values.get(f"ZEBRA_PUBLIC_OUTPUT_{field.name.upper()}")
        if raw is not None:
            settings[field.name] = type(getattr(defaults, field.name))(raw)
    return PublicOutputPolicy(**settings)
