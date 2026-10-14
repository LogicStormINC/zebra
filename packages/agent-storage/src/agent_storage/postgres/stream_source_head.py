"""Fresh bounded cloud observation metadata; never durable authority."""

from typing import Any
from uuid import UUID

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.stream_source_head import StreamCheckpointHead, StreamSourceHead
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCheckpointHead,
)
from agent_core.ports.task_replay import TaskReadHeader

# ponytail: qualification remains O(history), under the caller's cumulative 2s
# TaskIO deadline. A separately governed prefix proof is the upgrade path.
SOURCE_BODY = """
task AS (
 SELECT t.task_id,t.deployment_namespace,t.active_segment_id,t.next_event_sequence,
 t.event_position_state,h.title,h.status,h.current_sequence AS active_segment_sequence,
 h.title_truncated,h.clarification_id,h.clarification_invalid
 FROM args a JOIN agent_tasks t ON t.deployment_namespace=a.ns AND t.task_id=
 COALESCE(a.tid,(SELECT task_id FROM execution_segments WHERE deployment_namespace=a.ns
 AND session_id=a.sid))
 LEFT JOIN session_observation_headers h ON h.deployment_namespace=t.deployment_namespace
 AND h.session_id=t.active_segment_id::text
), members AS (
 SELECT m.session_id,m.predecessor_id,m.segment_index,m.event_position_source_ready,
 m.event_position_source_cursor,s.current_version FROM task t JOIN execution_segments m
 ON m.deployment_namespace=t.deployment_namespace AND m.task_id=t.task_id
 LEFT JOIN session_streams s ON s.deployment_namespace=m.deployment_namespace
 AND s.session_id=m.session_id ORDER BY m.segment_index LIMIT 257
), source AS (
 SELECT e.task_id,e.task_sequence,e.session_id,e.sequence,e.replay_header_ready,e.event_bytes_bound,
 m.event_position_source_cursor,
 (e.event_type='session_handoff_received' AND (m.predecessor_id IS NULL
 OR jsonb_typeof(e.payload->'root_session_id') IS DISTINCT FROM 'string'
 OR e.payload->>'root_session_id' IS DISTINCT FROM t.task_id::text
 OR jsonb_typeof(e.payload->'parent_session_id') IS DISTINCT FROM 'string'
 OR e.payload->>'parent_session_id' IS DISTINCT FROM m.predecessor_id::text
 OR jsonb_typeof(e.payload->'stage_index') IS DISTINCT FROM 'number'
 OR e.payload->>'stage_index' IS DISTINCT FROM m.segment_index::text)) AS invalid_origin,
 i.event_id AS indexed_event_id,i.task_id AS indexed_task_id,
 i.task_sequence AS indexed_task_sequence,i.segment_id AS indexed_segment_id,
 i.segment_sequence AS indexed_segment_sequence,
 row_number() OVER (PARTITION BY e.session_id ORDER BY e.task_sequence)-1 AS position
 FROM task t JOIN execution_segments m ON m.deployment_namespace=t.deployment_namespace
 AND m.task_id=t.task_id JOIN session_events e ON e.deployment_namespace=m.deployment_namespace
 AND e.session_id=m.session_id LEFT JOIN task_event_index i
 ON i.deployment_namespace=e.deployment_namespace AND i.event_id=e.event_id
), proof AS (
 SELECT count(*) AS count,min(e.task_sequence) AS first,max(e.task_sequence) AS last,
 bool_and(e.task_id=t.task_id AND e.task_sequence IS NOT NULL AND e.replay_header_ready
 AND e.event_bytes_bound IS NOT NULL AND e.indexed_event_id IS NOT NULL
 AND e.indexed_task_id=e.task_id AND e.indexed_task_sequence=e.task_sequence
 AND e.indexed_segment_id=e.session_id AND e.indexed_segment_sequence=e.sequence) AS valid,
 bool_or(e.sequence<>e.position OR e.sequence>e.event_position_source_cursor) AS invalid_order,
 bool_or(e.invalid_origin) AS invalid_origin
 FROM source e CROSS JOIN task t
)
SELECT t.*,p.*,(SELECT jsonb_agg(to_jsonb(m) ORDER BY m.segment_index) FROM members m) AS members,
 (SELECT count(*) FROM task_event_index i WHERE i.deployment_namespace=t.deployment_namespace
 AND i.task_id=t.task_id) AS indexed,
 (SELECT count(*) FROM session_events e WHERE e.deployment_namespace=t.deployment_namespace
 AND e.task_id=t.task_id) AS sourced,
 EXISTS(SELECT 1 FROM task_replay_coverage_privacy c
 WHERE c.deployment_namespace=t.deployment_namespace AND c.task_id=t.task_id) AS strict_coverage,
 sh.status AS session_status,sh.current_sequence AS session_observation_sequence,
 ss.current_version AS session_sequence
FROM task t CROSS JOIN proof p CROSS JOIN args a
LEFT JOIN session_observation_headers sh ON sh.deployment_namespace=a.ns
AND sh.session_id=a.sid::text
LEFT JOIN session_streams ss ON ss.deployment_namespace=a.ns AND ss.session_id=a.sid
"""


def source_row(
    connection: Any, namespace: str, task_id: TaskId | None, session_id: SessionId | None = None
) -> Any:
    return connection.execute(
        "WITH args AS (SELECT %s::text ns,%s::uuid tid,%s::uuid sid)," + SOURCE_BODY,
        (namespace, task_id, session_id),
    ).fetchone()


def qualify_source(row: Any) -> bool:
    if row["event_position_state"] != "ready":
        raise CheckpointNotReady("Task Event positions require explicit backfill")
    if row["status"] is None or row["active_segment_sequence"] is None:
        raise CheckpointNotReady("stream observation header requires explicit preparation")
    members = row["members"] or []
    if not members or len(members) > 256:
        raise CheckpointNotReady("stream membership requires a bounded canonical prefix")
    if members[0]["session_id"] != str(row["task_id"]) or str(row["active_segment_id"]) not in {
        member["session_id"] for member in members
    }:
        raise CheckpointConflict("stream Task membership conflicts with root or active Segment")
    expected = 0
    for index, member in enumerate(members):
        if member["segment_index"] != index or member["predecessor_id"] != (
            members[index - 1]["session_id"] if index else None
        ):
            raise CheckpointConflict("stream Segment lineage is incomplete or contradictory")
        if not member["event_position_source_ready"]:
            raise CheckpointNotReady("stream Segment source requires explicit backfill")
        highwater = member["current_version"]
        if highwater is None or member["event_position_source_cursor"] != highwater:
            raise CheckpointConflict("stream Segment frontier conflicts with canonical source")
        if member["session_id"] == str(row["active_segment_id"]) and (
            row["active_segment_sequence"] != highwater
        ):
            raise CheckpointNotReady("stream observation header is behind canonical source")
        expected += highwater + 1
    if expected != row["next_event_sequence"]:
        raise CheckpointConflict("stream Task highwater omits canonical Segment coverage")
    if (row["count"], row["first"], row["last"], row["valid"]) != (expected, 0, expected - 1, True):
        raise CheckpointConflict("stream Task index conflicts with canonical source prefix")
    if row["indexed"] != expected or row["sourced"] != expected:
        raise CheckpointConflict("stream Task index contains non-member Events")
    if row["invalid_order"]:
        raise CheckpointConflict("stream Segment has a gap or conflicting Task order")
    if row["invalid_origin"]:
        raise CheckpointConflict("stream Task membership contradicts durable handoff origin")
    return bool(row["strict_coverage"])


def task_header(row: Any) -> TaskReadHeader:
    strict = qualify_source(row)
    return TaskReadHeader(
        TaskId(UUID(str(row["task_id"]))),
        SessionId(UUID(str(row["active_segment_id"]))),
        row["next_event_sequence"] - 1,
        title=row["title"],
        status=SessionStatus(row["status"]),
        active_segment_sequence=row["active_segment_sequence"],
        title_truncated=bool(row["title_truncated"]),
        clarification_id=row["clarification_id"],
        clarification_invalid=bool(row["clarification_invalid"]),
        strict_coverage=strict,
    )


def read_source_head(
    connection: Any, namespace: str, task_id: TaskId | None, session_id: SessionId | None = None
) -> StreamSourceHead | None:
    if (task_id is None) == (session_id is None) or not isinstance(task_id or session_id, UUID):
        raise ValueError("stream head requires one canonical Task or Session identity")
    row = source_row(connection, namespace, task_id, session_id)
    if row is None:
        return None
    header = task_header(row)
    if session_id is not None and (
        row["session_status"] is None
        or row["session_sequence"] is None
        or row["session_observation_sequence"] != row["session_sequence"]
    ):
        raise CheckpointNotReady("requested Session observation is behind canonical source")
    return StreamSourceHead(
        header,
        row["session_sequence"],
        SessionStatus(row["session_status"]) if session_id is not None else None,
    )


def read_checkpoint_source_head(
    connection: Any,
    namespace: str,
    task_id: TaskId,
    run_id: str,
    *,
    ordinary_version: str,
    coverage_version: str,
    host_context: HostContextEnvelope | None = None,
) -> StreamCheckpointHead:
    from agent_core.contracts.broker_envelope import PrincipalScope
    from agent_core.ports.task_projection_checkpoints import ProjectionScope

    from agent_storage.postgres.command_wakeup import command_scope_key
    from agent_storage.postgres.command_wakeup_outcome import (
        COMMAND_OUTCOME_BODY,
        command_outcome_from_row,
    )
    from agent_storage.postgres.command_wakeup_receipts import HANDLED_EVENTS
    from agent_storage.postgres.task_projection_checkpoint_rows import (
        CHECKPOINT_HEAD_BODY,
        checkpoint_head_from_row,
    )
    from agent_storage.postgres.task_replay_headers import RUN_HEADER_BODY, run_header_from_row

    if not isinstance(run_id, str) or not run_id or len(run_id) > 256:
        raise ValueError("invalid replay Run identity")
    if not isinstance(task_id, UUID):
        raise ValueError("stream head requires one canonical Task or Session identity")
    principal = (
        PrincipalScope(
            kind="principal",
            tenant_id=host_context.namespace_id,
            workspace_id=host_context.workspace_ref,
        )
        if host_context is not None
        else None
    )
    row = connection.execute(
        "SELECT to_jsonb(s) AS source,to_jsonb(r) AS run,to_jsonb(h) AS head,"
        "to_jsonb(o) AS outcome FROM (SELECT %s::text ns,%s::uuid tid,%s::text rid,"
        "%s::text ordinary,%s::text coverage,%s::boolean outcome_enabled,"
        "%s::text scope_key,%s::text tenant,%s::text workspace,%s::text[] handled) request "
        "LEFT JOIN LATERAL (WITH args AS (SELECT request.ns,request.tid,NULL::uuid sid),"
        + SOURCE_BODY
        + ") s ON true "
        "LEFT JOIN LATERAL (WITH args AS (SELECT request.ns,request.tid,request.rid,"
        "NULL::bigint through)," + RUN_HEADER_BODY + ") r ON true "
        "LEFT JOIN LATERAL (WITH args AS (SELECT request.ns,request.tid,"
        "COALESCE(r.commands->0->>'event_id','') anchor,"
        "CASE WHEN r.strict_coverage THEN request.coverage ELSE request.ordinary END version,"
        "(r.executable OR r.first_command IS NULL) enabled),"
        + CHECKPOINT_HEAD_BODY
        + ") h ON true "
        "LEFT JOIN LATERAL (WITH args AS (SELECT request.ns,request.tid,request.rid,"
        "(r.commands->0->>'task_sequence')::bigint position,"
        "(r.commands->0->>'event_id')::uuid eid,(r.commands->0->>'session_id')::uuid sid,"
        "(r.commands->0->>'sequence')::bigint sequence,"
        "(r.commands IS NOT NULL AND NOT r.executable) control_only,"
        "request.scope_key,request.tenant,request.workspace,request.handled,"
        "(request.outcome_enabled AND r.commands IS NOT NULL) enabled),"
        + COMMAND_OUTCOME_BODY
        + ") o ON true",
        (
            namespace,
            task_id,
            run_id,
            ordinary_version,
            coverage_version,
            host_context is not None,
            command_scope_key(principal) if principal is not None else None,
            principal.tenant_id if principal is not None else None,
            principal.workspace_id if principal is not None else None,
            [event.value for event in HANDLED_EVENTS],
        ),
    ).fetchone()
    if row["source"] is None:
        raise CheckpointConflict("Task replay target was not found")
    source = task_header(row["source"])
    run = run_header_from_row(row["run"], task_id, run_id)
    if run.highwater != source.current_sequence or run.strict_coverage != source.strict_coverage:
        raise CheckpointConflict("observation Run conflicts with qualified source")
    scope = ProjectionScope(
        namespace,
        task_id,
        run.anchor.event_id if run.anchor else None,
        coverage_version if run.strict_coverage else ordinary_version,
    )
    head = (
        ProjectionCheckpointHead(scope)
        if run.control_only or (not run.legacy and run.anchor is None)
        else checkpoint_head_from_row(row["head"], scope)
    )
    outcome = (
        command_outcome_from_row(connection, namespace, run, host_context, row["outcome"])
        if host_context is not None and run.anchor is not None
        else None
    )
    return StreamCheckpointHead(run, head, outcome)
