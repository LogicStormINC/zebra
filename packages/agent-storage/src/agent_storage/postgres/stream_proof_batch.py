"""Explicit fresh stream-proof snapshot; existing source predicates own qualification."""

from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic
from typing import Any

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.leases import WorkerLease
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.agent_tasks import TaskEventPage
from agent_core.ports.task_replay import TaskEventHeader, TaskReadHeader, TaskRunHeader

from agent_storage.postgres.agent_tasks import read_task_header
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import read_current_lease
from agent_storage.postgres.task_admission import read_session_task_binding
from agent_storage.postgres.task_event_pages import read_task_event_page
from agent_storage.postgres.task_io import task_io_deadline
from agent_storage.postgres.task_replay_headers import (
    read_event_header,
    read_latest_run_header,
    read_run_header,
)
from agent_storage.postgres.worker_replay_reader import AUTHORITY_TYPES, read_worker_events


class StreamProofSnapshot:
    """Connection-bound readonly operations; never survives its context manager.

    ponytail: this shares a transaction, not mutable authority results. Existing
    source qualification remains O(history), bounded by the same 2s deadline.
    """

    def __init__(self, connection: Any, namespace: str) -> None:
        self._connection, self._namespace = connection, namespace

    def read_task_header(
        self, task_id: TaskId, *, require_source_coverage: bool = False
    ) -> TaskReadHeader | None:
        return read_task_header(
            self._connection,
            self._namespace,
            task_id,
            require_source_coverage=require_source_coverage,
        )

    def read_run_header(
        self, task_id: TaskId, run_id: str, *, through_sequence: int | None = None
    ) -> TaskRunHeader:
        return read_run_header(self._connection, self._namespace, task_id, run_id, through_sequence)

    def read_latest_run_header(self, task_id: TaskId) -> TaskRunHeader:
        return read_latest_run_header(self._connection, self._namespace, task_id)

    def read_event_header(self, task_id: TaskId, task_sequence: int) -> TaskEventHeader | None:
        return read_event_header(self._connection, self._namespace, task_id, task_sequence)

    def read_event_page(
        self,
        task_id: TaskId,
        after_sequence: int,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
        through_sequence: int | None = None,
    ) -> TaskEventPage:
        return read_task_event_page(
            self._connection,
            self._namespace,
            task_id,
            after_sequence,
            limit=limit,
            max_bytes=max_bytes,
            through=through_sequence,
        )

    def authority_events(self, session_id: SessionId) -> list[SessionEvent]:
        return read_worker_events(self._connection, self._namespace, session_id, AUTHORITY_TYPES)

    def binding(self, session_id: SessionId) -> TaskBindingSnapshot | None:
        return read_session_task_binding(self._connection, self._namespace, session_id)

    def get(self, session_id: SessionId) -> WorkerLease | None:
        return read_current_lease(self._connection, self._namespace, session_id)


class StreamProofReader:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @contextmanager
    def snapshot(self) -> Iterator[StreamProofSnapshot]:
        # connect_task_io is deliberately fresh, even inside another phase's
        # snapshot/work unit. DNS/query/cancel/commit/release share this budget.
        with task_io_deadline(monotonic() + 2), self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield StreamProofSnapshot(connection, self._database.deployment_namespace)
