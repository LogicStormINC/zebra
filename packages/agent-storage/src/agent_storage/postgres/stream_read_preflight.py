"""Read-only canonical prefix validation before any public stream body hydration."""

from typing import Any

from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady


def require_stream_source(connection: Any, namespace: str, task_id: TaskId, task: Any) -> bool:
    # ponytail: metadata integrity remains O(history) SQL under the caller's 2s
    # TaskIO deadline. A separately governed prefix proof is the upgrade path;
    # frontier/cache assertions cannot replace intact canonical membership.
    members = connection.execute(
        "SELECT m.session_id,m.predecessor_id,m.segment_index,m.event_position_source_ready,"
        "m.event_position_source_cursor,s.current_version FROM execution_segments m "
        "LEFT JOIN session_streams s ON s.deployment_namespace=m.deployment_namespace "
        "AND s.session_id=m.session_id WHERE m.deployment_namespace=%s AND m.task_id=%s "
        "ORDER BY m.segment_index LIMIT 257",
        (namespace, task_id),
    ).fetchall()
    if not members or len(members) > 256:
        raise CheckpointNotReady("stream membership requires a bounded canonical prefix")
    if members[0]["session_id"] != task_id or task["active_segment_id"] not in {
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
        if member["session_id"] == task["active_segment_id"] and (
            task["active_segment_sequence"] != highwater
        ):
            raise CheckpointNotReady("stream observation header is behind canonical source")
        expected += highwater + 1
    if expected != task["next_event_sequence"]:
        raise CheckpointConflict("stream Task highwater omits canonical Segment coverage")
    row = connection.execute(
        "SELECT count(*) AS count,min(e.task_sequence) AS first,max(e.task_sequence) AS last,"
        "bool_and(e.task_id=%s AND e.task_sequence IS NOT NULL "
        "AND e.replay_header_ready "
        "AND e.event_bytes_bound IS NOT NULL AND i.event_id IS NOT NULL "
        "AND i.task_id=e.task_id AND i.task_sequence=e.task_sequence "
        "AND i.segment_id=e.session_id AND i.segment_sequence=e.sequence) AS valid "
        "FROM execution_segments m JOIN session_events e "
        "ON e.deployment_namespace=m.deployment_namespace AND e.session_id=m.session_id "
        "LEFT JOIN task_event_index i ON i.deployment_namespace=e.deployment_namespace "
        "AND i.event_id=e.event_id WHERE m.deployment_namespace=%s AND m.task_id=%s",
        (task_id, namespace, task_id),
    ).fetchone()
    if (row["count"], row["first"], row["last"], row["valid"]) != (expected, 0, expected - 1, True):
        raise CheckpointConflict("stream Task index conflicts with canonical source prefix")
    counts = connection.execute(
        "SELECT (SELECT count(*) FROM task_event_index WHERE deployment_namespace=%s "
        "AND task_id=%s) AS indexed,(SELECT count(*) FROM session_events "
        "WHERE deployment_namespace=%s AND task_id=%s) AS sourced",
        (namespace, task_id, namespace, task_id),
    ).fetchone()
    if counts["indexed"] != expected or counts["sourced"] != expected:
        raise CheckpointConflict("stream Task index contains non-member Events")
    invalid = connection.execute(
        "SELECT 1 FROM (SELECT e.sequence,m.event_position_source_cursor,"
        "row_number() OVER (PARTITION BY e.session_id ORDER BY e.task_sequence)-1 AS position "
        "FROM execution_segments m JOIN session_events e "
        "ON e.deployment_namespace=m.deployment_namespace AND e.session_id=m.session_id "
        "WHERE m.deployment_namespace=%s AND m.task_id=%s) prefix "
        "WHERE sequence<>position OR sequence>event_position_source_cursor LIMIT 1",
        (namespace, task_id),
    ).fetchone()
    if invalid is not None:
        raise CheckpointConflict("stream Segment has a gap or conflicting Task order")
    # Only handoff scalar expressions inspect JSON in the database. Historical
    # model/tool payloads never transfer or hydrate, even during prefix proof.
    invalid = connection.execute(
        "SELECT 1 FROM execution_segments m JOIN session_events e "
        "ON e.deployment_namespace=m.deployment_namespace AND e.session_id=m.session_id "
        "WHERE m.deployment_namespace=%s AND m.task_id=%s "
        "AND e.event_type='session_handoff_received' AND (m.predecessor_id IS NULL "
        "OR jsonb_typeof(e.payload->'root_session_id') IS DISTINCT FROM 'string' "
        "OR e.payload->>'root_session_id' IS DISTINCT FROM %s "
        "OR jsonb_typeof(e.payload->'parent_session_id') IS DISTINCT FROM 'string' "
        "OR e.payload->>'parent_session_id' IS DISTINCT FROM m.predecessor_id::text "
        "OR jsonb_typeof(e.payload->'stage_index') IS DISTINCT FROM 'number' "
        "OR e.payload->>'stage_index' IS DISTINCT FROM m.segment_index::text) LIMIT 1",
        (namespace, task_id, str(task_id)),
    ).fetchone()
    if invalid is not None:
        raise CheckpointConflict("stream Task membership contradicts durable handoff origin")
    row = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM task_replay_coverage_privacy "
        "WHERE deployment_namespace=%s AND task_id=%s) AS strict_coverage",
        (namespace, task_id),
    ).fetchone()
    return bool(row["strict_coverage"])
