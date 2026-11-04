"""Opt-in receipt proof for the isolated E1 replication fixture."""

import os
from dataclasses import replace
from functools import lru_cache

from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_storage.postgres.capacity_profile import CapacityProfile
from agent_storage.postgres.connection_capacity import PROFILE_ENV, ConnectionBudget, capacity_lane
from agent_storage.postgres.task_io import TaskIoConnections
from psycopg import Error
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

_ENV = "ZEBRA_HA_E1_RECEIPT_PROOF_DSN"
_IDENTITY = "ZEBRA_HA_E1_RECEIPT_PROOF_SYSTEM_ID"
_TIMELINE = "ZEBRA_HA_E1_RECEIPT_PROOF_TIMELINE"


def enabled() -> bool:
    return any(key in os.environ for key in (_ENV, _IDENTITY, _TIMELINE))


@lru_cache(maxsize=1)
def _connector(dsn: str, inventory: str) -> TaskIoConnections:
    profile = replace(CapacityProfile.parse(inventory), normal=1)
    # The isolated standby role enforces the fleet ceiling independently.
    return TaskIoConnections(dsn, budget=ConnectionBudget(dsn, profile, "api"))


def confirmed(namespace: str, record: IdempotencyRecord | None) -> bool:
    if not enabled():
        return True
    if record is None:
        return False
    dsn = os.environ.get(_ENV, "")
    identity = os.environ.get(_IDENTITY, "")
    timeline = os.environ.get(_TIMELINE, "")
    try:
        params = conninfo_to_dict(dsn)
        if (
            not identity.isascii()
            or not identity.isdecimal()
            or not timeline.isascii()
            or not timeline.isdecimal()
            or params.get("sslmode") != "verify-full"
            or params.get("user") != "e1_receipt_reader"
            or not params.get("host")
            or "," in params["host"]
            or params.get("service")
        ):
            return False
        connector = _connector(dsn, os.environ.get(PROFILE_ENV, ""))
        with capacity_lane("normal"), connector.connect(timeout_seconds=0.5) as connection:
            row = connection.execute(
                """SELECT public.e1_confirm_receipt(%s,%s,%s,%s,%s,%s,%s,%s) AS confirmed""",
                (
                    identity,
                    timeline,
                    namespace,
                    record.action,
                    record.idempotency_key,
                    record.request_hash,
                    record.status_code,
                    Jsonb(record.response_body),
                ),
            ).fetchone()
            return row is not None and row["confirmed"] is True
    except (Error, TimeoutError, ValueError, RuntimeError):
        return False
