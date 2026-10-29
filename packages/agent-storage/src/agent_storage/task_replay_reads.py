"""SQLite body-free replay query composition."""

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader

from agent_storage.database import SQLiteDatabase
from agent_storage.task_replay_headers import (
    read_event_header,
    read_event_header_by_key,
    read_run_header,
)


class SQLiteTaskReplayReadMixin:
    _database: SQLiteDatabase

    def read_event_header(self, task_id: TaskId, task_sequence: int) -> TaskEventHeader | None:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            return read_event_header(connection, task_id, task_sequence)

    def read_run_header(
        self,
        task_id: TaskId,
        run_id: str,
        *,
        through_sequence: int | None = None,
    ) -> TaskRunHeader:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            return read_run_header(connection, task_id, run_id, through_sequence)

    def read_event_header_by_key(
        self, task_id: TaskId, segment_id: SessionId, idempotency_key: str
    ) -> TaskEventHeader | None:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            return read_event_header_by_key(connection, task_id, segment_id, idempotency_key)
