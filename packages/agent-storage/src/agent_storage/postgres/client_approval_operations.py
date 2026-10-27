"""Use existing stream CAS/unique event key; no schema or historical rewrite."""

from collections.abc import Iterator
from contextlib import contextmanager

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.work_unit import postgres_transaction_work_unit


@contextmanager
def operation_unit(db: PostgresDatabase, segment: SessionId) -> Iterator[None]:
    with db.connect() as connection:
        connection.execute("SELECT set_config('lock_timeout','1500ms',true)")
        row = connection.execute(
            "SELECT current_version FROM session_streams "
            "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
            (db.deployment_namespace, segment),
        ).fetchone()
        if row is None:
            raise ValueError("approval stream unavailable")
        with postgres_transaction_work_unit(db, connection):
            yield


def read_operation(db: PostgresDatabase, segment: SessionId, key: str) -> SessionEvent | None:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT event_id,session_id,sequence,event_type,actor,created_at,causation_id,"
            "correlation_id,idempotency_key,policy_version,model_profile,"
            "CASE WHEN octet_length(payload::text)<=8192 THEN payload ELSE NULL END AS payload "
            "FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
            "AND idempotency_key=%s AND event_type IN ('approval_granted','approval_rejected') "
            "LIMIT 1",
            (db.deployment_namespace, segment, key),
        ).fetchone()
    return None if row is None else SessionEvent.model_validate(row)
