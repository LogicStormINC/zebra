"""Bounded legacy discovery; never changes command cutover or projects an intent."""

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.projections import _session_from_row

LEGACY_REJECTION_ACTION = "worker.legacy-command.rejected.v1"

# An exact accepted Event is immutable. Rejections never advance the Session projection.
_UNREJECTED = """NOT EXISTS (
    SELECT 1 FROM control_plane_idempotency_records r
    WHERE r.deployment_namespace=e.deployment_namespace
      AND r.action=%s AND r.idempotency_key=e.event_id::text
)"""


class LegacyCommandCandidates:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def __call__(self, limit: int, after: SessionId | None) -> list[Session]:
        if not 1 <= limit <= 500:
            raise ValueError("legacy command discovery limit must be between 1 and 500")
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""SELECT p.* FROM session_projections p
                WHERE p.deployment_namespace=%s
                  AND (%s::uuid IS NULL OR p.session_id > %s::uuid)
                  AND EXISTS (
                    SELECT 1 FROM session_events e
                    WHERE e.deployment_namespace=p.deployment_namespace
                      AND e.session_id=p.session_id AND e.sequence > p.current_sequence
                      AND e.event_type='session_command_accepted'
                      AND {_UNREJECTED}
                  )
                ORDER BY p.session_id LIMIT %s""",
                (self._database.deployment_namespace, after, after, LEGACY_REJECTION_ACTION, limit),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def next_command(self, session_id: SessionId, current_sequence: int) -> SessionEvent | None:
        # STOP/CANCEL bypass prior execution intents, as in the migrated control lane.
        with self._database.connect() as connection:
            row = connection.execute(
                f"""SELECT e.* FROM session_events e
                WHERE e.deployment_namespace=%s AND e.session_id=%s AND e.sequence>%s
                  AND e.event_type='session_command_accepted' AND {_UNREJECTED}
                ORDER BY COALESCE(e.payload->>'kind' IN ('stop','cancel'), false) DESC,
                         e.sequence LIMIT 1""",
                (self._database.deployment_namespace, session_id, current_sequence,
                 LEGACY_REJECTION_ACTION),
            ).fetchone()
        return None if row is None else SessionEvent.model_validate(row)
