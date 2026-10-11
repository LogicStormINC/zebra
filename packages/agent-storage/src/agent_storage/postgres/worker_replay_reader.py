"""Bounded canonical evidence for MCP frames and governed Memory finalization.

No projection, capsule, or cached latest snapshot substitutes for raw evidence.
The additive seek index must be registered/applied by the composition owner.
"""

import json
from time import monotonic
from typing import Any

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.session_recovery import SessionEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.session_recovery import read_session_page
from agent_storage.postgres.task_io import task_io_deadline
from agent_storage.postgres.task_lineage import EVENT_COLUMNS

WORKER_REPLAY_INDEX_SQL = """CREATE INDEX session_events_worker_replay
    ON session_events(deployment_namespace,session_id,event_type,sequence)
    INCLUDE(event_bytes_bound)"""

# Every event observed by current_turn/latest_authority_snapshot, including
# non-current closures and denial/reset events. Never select only the last Grant.
AUTHORITY_TYPES = (
    EventType.USER_MESSAGE_RECEIVED,
    EventType.TURN_COMPLETED,
    EventType.TURN_FAILED,
    EventType.TURN_CANCELLED,
    EventType.SESSION_COMPLETED,
    EventType.SESSION_FAILED,
    EventType.SESSION_CANCELLED,
    EventType.APPROVAL_REQUESTED,
    EventType.APPROVAL_GRANTED,
    EventType.CLARIFICATION_REQUESTED,
    EventType.CLARIFICATION_RESPONDED,
    EventType.EXECUTION_AUTHORITY_RESOLVED,
    EventType.EXECUTION_AUTHORITY_REVALIDATED,
)

# Retain old file-read evidence too: refresh_target_applies reconstructs old
# candidates from their original source Event, even before the extraction window.
MEMORY_TYPES = (
    EventType.TASK_PREPARED,
    EventType.USER_MESSAGE_RECEIVED,
    EventType.TOOL_EXECUTION_COMPLETED,
    EventType.MODEL_RESPONSE_RECEIVED,
    EventType.TURN_COMPLETED,
    EventType.SESSION_COMPLETED,
    EventType.MEMORY_EXTRACTION_COMPLETED,
    EventType.MEMORY_CANDIDATE_EXTRACTED,
    EventType.MEMORY_REVIEW_RECORDED,
    EventType.SESSION_TITLE_UPDATED,
)


class WorkerReplayLimitExceeded(CheckpointNotReady):
    """Exact evidence exceeds admission; never return a silently truncated chain."""


class PostgresWorkerReplayReader:
    """One captured highwater/2s scope; pages <=256 Events/1MiB.

    ponytail: exact relevant evidence has a 2048-Event/1MiB ceiling, matching
    execution inputs. Larger chains fail closed; a separately proven canonical
    authority/window reducer is required before this ceiling can be lifted.
    """

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def authority_events(self, session_id: SessionId) -> list[SessionEvent]:
        return self._read(session_id, AUTHORITY_TYPES)

    def tail_page(
        self, authority: WorkerMutationAuthority, through: int | None = None
    ) -> SessionEventPage:
        """Seek only the recorder's exact tail, not historical relevant evidence."""
        namespace = self._database.deployment_namespace
        if authority.deployment_namespace != namespace:
            raise LeaseLostError("Worker tail authority crosses namespace")
        with task_io_deadline(monotonic() + 2), self._database.connect_task_io() as connection:
            assert_current_lease_fence(
                connection, namespace, authority.session_id, authority.lease_fence
            )
            source = connection.execute(
                "SELECT current_version FROM session_streams "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (namespace, authority.session_id),
            ).fetchone()
            if source is None:
                raise CheckpointNotReady("Worker tail Session is absent")
            page = read_session_page(
                connection,
                namespace,
                authority.session_id,
                authority.expected_stream_revision,
                through=source["current_version"] if through is None else through,
            )
            assert_current_lease_fence(
                connection, namespace, authority.session_id, authority.lease_fence
            )
            return page

    def memory_events(
        self, session_id: SessionId, *, authority: WorkerMutationAuthority
    ) -> list[SessionEvent]:
        return self._read(
            session_id,
            MEMORY_TYPES,
            through=authority.expected_stream_revision,
            authority=authority,
        )

    def receipt_events(
        self,
        session_id: SessionId,
        *,
        after: int,
        through: int,
        authority: WorkerMutationAuthority,
    ) -> list[SessionEvent]:
        return self._read(session_id, None, after=after, through=through, authority=authority)

    def _read(
        self,
        session_id: SessionId,
        types: tuple[EventType, ...] | None,
        *,
        after: int = -1,
        through: int | None = None,
        authority: WorkerMutationAuthority | None = None,
    ) -> list[SessionEvent]:
        namespace = self._database.deployment_namespace
        if authority is not None and (
            authority.deployment_namespace != namespace or authority.session_id != session_id
        ):
            raise LeaseLostError("Worker replay authority crosses namespace/Session")
        with task_io_deadline(monotonic() + 2), self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            if authority is not None:
                assert_current_lease_fence(connection, namespace, session_id, authority.lease_fence)
            source = connection.execute(
                "SELECT current_version FROM session_streams "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (namespace, session_id),
            ).fetchone()
            if source is None:
                raise CheckpointNotReady("Worker replay Session is absent")
            highwater = source["current_version"] if through is None else through
            if (
                type(highwater) is not int
                or not -1 <= after <= highwater <= source["current_version"]
            ):
                raise ValueError("Worker replay range conflicts with canonical source")
            result: list[SessionEvent] = []
            size = 0
            while after < highwater:
                page = (
                    list(
                        read_session_page(
                            connection, namespace, session_id, after, through=highwater
                        ).events
                    )
                    if types is None
                    else _typed_page(connection, namespace, session_id, types, after, highwater)
                )
                if not page:
                    break
                size += sum(len(_encoded(event)) for event in page)
                if len(result) + len(page) > 2048 or size > 1_048_576:
                    raise WorkerReplayLimitExceeded("exact Worker replay exceeds 2048 Events/1MiB")
                result.extend(page)
                after = page[-1].sequence
            if authority is not None:
                assert_current_lease_fence(connection, namespace, session_id, authority.lease_fence)
            return result


def _encoded(event: SessionEvent) -> bytes:
    return json.dumps(
        event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    ).encode()


def _typed_page(
    connection: Any,
    namespace: str,
    session_id: SessionId,
    types: tuple[EventType, ...],
    after: int,
    through: int,
) -> list[SessionEvent]:
    # Each type is an indexed seek with a bounded LIMIT BEFORE the merge/sort.
    # A broad event_type=ANY ORDER BY sequence can scan a whole old Session.
    metadata = connection.execute(
        "SELECT selected.sequence,selected.event_bytes_bound FROM unnest(%s::text[]) kind "
        "CROSS JOIN LATERAL (SELECT sequence,event_bytes_bound FROM session_events "
        "WHERE deployment_namespace=%s AND session_id=%s AND event_type=kind "
        "AND sequence>%s AND sequence<=%s ORDER BY sequence LIMIT 256) selected "
        "ORDER BY selected.sequence LIMIT 256",
        ([event_type.value for event_type in types], namespace, session_id, after, through),
    ).fetchall()
    positions: list[int] = []
    size = 0
    for row in metadata:
        bound = row["event_bytes_bound"]
        if type(bound) is not int or bound <= 0:
            raise CheckpointNotReady("Worker replay requires prepared Event byte bounds")
        if size + bound > 1_048_576:
            if not positions:
                raise WorkerReplayLimitExceeded("canonical Worker evidence exceeds 1MiB/page")
            break
        positions.append(row["sequence"])
        size += bound
    if not positions:
        return []
    rows = connection.execute(
        f"SELECT {EVENT_COLUMNS} FROM session_events event "
        "WHERE deployment_namespace=%s AND session_id=%s AND sequence=ANY(%s::bigint[]) "
        "ORDER BY sequence",
        (namespace, session_id, positions),
    ).fetchall()
    events = [SessionEvent.model_validate(row) for row in rows]
    if [event.sequence for event in events] != positions or sum(
        map(len, map(_encoded, events))
    ) > size:
        raise ValueError("Worker evidence page conflicts with admission metadata")
    return events
