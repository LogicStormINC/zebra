"""Additive derived summary storage; no source adoption or GET-side initialization."""

import sqlite3


def task_read_summary_schema(*, postgres: bool = False) -> tuple[str, ...]:
    identity = "UUID" if postgres else "TEXT"
    usage_bytes = (
        "octet_length(usage_state_json)" if postgres else "length(CAST(usage_state_json AS BLOB))"
    )
    ref_bytes = "octet_length(ref_json)" if postgres else "length(CAST(ref_json AS BLOB))"
    source_fk = (
        "FOREIGN KEY(deployment_namespace,task_id) REFERENCES "
        "agent_tasks(deployment_namespace,task_id) ON DELETE CASCADE"
        if postgres
        else "FOREIGN KEY(task_id) REFERENCES agent_tasks(task_id) ON DELETE CASCADE"
    )
    return (
        f"""CREATE TABLE IF NOT EXISTS task_read_summary_heads (
            deployment_namespace TEXT NOT NULL, task_id {identity} NOT NULL,
            through_sequence BIGINT NOT NULL DEFAULT -1 CHECK(through_sequence>=-1),
            usage_state_json TEXT NOT NULL DEFAULT '{{}}'
              CHECK({usage_bytes}<=65536),
            attachment_count BIGINT NOT NULL DEFAULT 0 CHECK(attachment_count>=0),
            attachment_bytes BIGINT NOT NULL DEFAULT 0 CHECK(attachment_bytes>=0),
            PRIMARY KEY(deployment_namespace,task_id), {source_fk})""",
        f"""CREATE TABLE IF NOT EXISTS task_read_summary_frontiers (
            deployment_namespace TEXT NOT NULL, task_id {identity} NOT NULL,
            task_sequence BIGINT NOT NULL CHECK(task_sequence>=0),
            event_id {identity} NOT NULL, segment_id {identity} NOT NULL,
            segment_sequence BIGINT NOT NULL CHECK(segment_sequence>=0),
            attachment_count BIGINT NOT NULL CHECK(attachment_count>=0),
            attachment_bytes BIGINT NOT NULL CHECK(attachment_bytes>=0),
            PRIMARY KEY(deployment_namespace,task_id,task_sequence),
            FOREIGN KEY(deployment_namespace,task_id) REFERENCES
              task_read_summary_heads(deployment_namespace,task_id) ON DELETE CASCADE)""",
        f"""CREATE TABLE IF NOT EXISTS task_attachment_index (
            deployment_namespace TEXT NOT NULL, task_id {identity} NOT NULL,
            ordinal BIGINT NOT NULL CHECK(ordinal>=0),
            task_sequence BIGINT NOT NULL CHECK(task_sequence>=0),
            attachment_index BIGINT NOT NULL CHECK(attachment_index>=0),
            ref_json TEXT NOT NULL, ref_bytes BIGINT NOT NULL
              CHECK(ref_bytes BETWEEN 1 AND 1048576 AND ref_bytes={ref_bytes}),
            PRIMARY KEY(deployment_namespace,task_id,ordinal),
            UNIQUE(deployment_namespace,task_id,task_sequence,attachment_index),
            FOREIGN KEY(deployment_namespace,task_id,task_sequence) REFERENCES
              task_read_summary_frontiers(deployment_namespace,task_id,task_sequence)
              ON DELETE CASCADE)""",
    )


def initialize_task_read_summaries(connection: sqlite3.Connection) -> None:
    for statement in task_read_summary_schema():
        connection.execute(statement)
