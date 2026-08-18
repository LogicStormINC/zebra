"""Shared error and psycopg helpers for the Agent Definition Registry (v19)."""

from __future__ import annotations

from typing import Any


class AgentRegistryStorageError(ValueError):
    """Raised for invalid Registry inputs or durable-state mismatches."""


def _Jsonb(value: Any) -> Any:  # noqa: N802 - psycopg helper
    from psycopg.types.json import Jsonb

    return Jsonb(value)
