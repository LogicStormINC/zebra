"""Write-owned scalar handoffs and contiguous blocks; installation reads no bodies."""

import sqlite3

from agent_storage.database import ensure_column


def _uuid(expression: str) -> str:
    raw = (
        f"lower(replace(replace(replace(replace({expression},'urn:uuid:',''),"
        "'-',''),'{',''),'}',''))"
    )
    return (
        f"CASE WHEN length({raw})=32 AND {raw} NOT GLOB '*[^0-9a-f]*' THEN "
        f"substr({raw},1,8)||'-'||substr({raw},9,4)||'-'||substr({raw},13,4)||'-'||"
        f"substr({raw},17,4)||'-'||substr({raw},21,12) END"
    )


_HANDOFF = "event_type IN ('session_handoff_committed','session_handoff_received')"
_HANDOFF_ID = _uuid("json_extract(payload,'$.handoff_id')")
_ID = f"CASE WHEN {_HANDOFF} THEN {_HANDOFF_ID} END"
_PEER = _uuid(
    "CASE event_type WHEN 'session_handoff_committed' THEN "
    "json_extract(payload,'$.target_session_id') WHEN 'session_handoff_received' "
    "THEN json_extract(payload,'$.parent_session_id') END"
)
BLOCK_COLUMNS = (
    "segment_id,first_task_sequence,last_task_sequence,first_segment_sequence,"
    "last_segment_sequence,previous_block_start"
)
HEADER_COLUMNS = (
    "task_id,task_sequence,event_id,session_id,sequence,event_type,"
    "projection_handoff_id,projection_peer_segment_id,projection_metadata_ready,"
    "projection_block_start"
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS task_projection_source_heads (
 deployment_namespace TEXT NOT NULL, task_id TEXT NOT NULL,
 through_sequence INTEGER NOT NULL DEFAULT -1 CHECK(through_sequence>=-1),
 repair_cursor INTEGER NOT NULL DEFAULT -1 CHECK(repair_cursor>=-1),
 repair_highwater INTEGER NOT NULL DEFAULT -1 CHECK(repair_highwater>=-1),
 PRIMARY KEY(deployment_namespace,task_id));
CREATE TABLE IF NOT EXISTS task_projection_blocks (
 deployment_namespace TEXT NOT NULL, task_id TEXT NOT NULL, segment_id TEXT NOT NULL,
 first_task_sequence INTEGER NOT NULL CHECK(first_task_sequence>=0),
 last_task_sequence INTEGER NOT NULL,
 first_segment_sequence INTEGER NOT NULL CHECK(first_segment_sequence>=0),
 last_segment_sequence INTEGER NOT NULL, previous_block_start INTEGER,
 PRIMARY KEY(deployment_namespace,task_id,first_task_sequence),
 CHECK(last_task_sequence>=first_task_sequence),
 CHECK(last_task_sequence-first_task_sequence=last_segment_sequence-first_segment_sequence),
 CHECK(previous_block_start IS NULL OR previous_block_start BETWEEN 0 AND first_task_sequence-1),
 CHECK((previous_block_start IS NULL)=(first_segment_sequence=0)));
CREATE INDEX IF NOT EXISTS task_projection_blocks_segment
 ON task_projection_blocks(deployment_namespace,task_id,segment_id,first_task_sequence);
CREATE INDEX IF NOT EXISTS session_events_projection_header
 ON session_events(task_id,task_sequence,event_id,session_id,sequence,event_type,
 projection_handoff_id,projection_peer_segment_id,projection_metadata_ready,projection_block_start);
CREATE INDEX IF NOT EXISTS session_events_projection_pending
 ON session_events(task_id,task_sequence)
 WHERE projection_metadata_ready=0 OR projection_block_start IS NULL;
CREATE INDEX IF NOT EXISTS session_events_projection_block
 ON session_events(task_id,projection_block_start,task_sequence,session_id,sequence);
CREATE INDEX IF NOT EXISTS session_events_projection_receive
 ON session_events(task_id,session_id,task_sequence,
 projection_handoff_id,projection_peer_segment_id)
 WHERE event_type='session_handoff_received';
CREATE INDEX IF NOT EXISTS session_events_projection_receive_identity
 ON session_events(task_id,session_id,projection_handoff_id,task_sequence)
 WHERE event_type='session_handoff_received';
CREATE INDEX IF NOT EXISTS session_events_projection_commit
 ON session_events(task_id,session_id,projection_handoff_id,
 task_sequence,projection_peer_segment_id)
 WHERE event_type='session_handoff_committed';
"""

# Every seek below is a point or an indexed extremum. NEW is the assigned row;
# import before membership only parses scalars and queues explicit backfill.
_SCOPE = (
    "deployment_namespace=(SELECT namespace FROM agent_tasks WHERE task_id=NEW.task_id) "
    "AND task_id=NEW.task_id"
)
_NEXT = (
    f"(SELECT through_sequence FROM task_projection_source_heads WHERE {_SCOPE})"
    "=NEW.task_sequence-1"
)
_PREVIOUS = (
    f"(SELECT first_task_sequence FROM task_projection_blocks WHERE {_SCOPE} "
    "AND segment_id=NEW.session_id ORDER BY first_task_sequence DESC LIMIT 1)"
)
_LAST = (
    f"(SELECT last_segment_sequence FROM task_projection_blocks WHERE {_SCOPE} "
    "AND segment_id=NEW.session_id ORDER BY first_task_sequence DESC LIMIT 1)"
)
_GLOBAL = (
    "(SELECT projection_block_start FROM session_events WHERE task_id=NEW.task_id "
    "AND task_sequence=NEW.task_sequence-1)"
)
_BUILD = f"""
 INSERT OR IGNORE INTO task_projection_source_heads(deployment_namespace,task_id)
 SELECT namespace,task_id FROM agent_tasks WHERE task_id=NEW.task_id;
 SELECT CASE WHEN {_NEXT} AND NEW.sequence!=COALESCE({_LAST}+1,0)
 THEN RAISE(ABORT,'projection metadata conflicts with source order') END;
 INSERT INTO task_projection_blocks
 (deployment_namespace,task_id,{BLOCK_COLUMNS})
 SELECT namespace,NEW.task_id,NEW.session_id,NEW.task_sequence,NEW.task_sequence,
 NEW.sequence,NEW.sequence,{_PREVIOUS} FROM agent_tasks WHERE task_id=NEW.task_id
 AND {_NEXT} AND NOT EXISTS (SELECT 1 FROM task_projection_blocks WHERE {_SCOPE}
 AND first_task_sequence={_GLOBAL} AND segment_id=NEW.session_id);
 UPDATE task_projection_blocks SET last_task_sequence=NEW.task_sequence,
 last_segment_sequence=NEW.sequence WHERE {_SCOPE} AND first_task_sequence={_GLOBAL}
 AND segment_id=NEW.session_id AND {_NEXT};
 UPDATE session_events SET projection_block_start=(SELECT first_task_sequence
 FROM task_projection_blocks WHERE {_SCOPE} AND segment_id=NEW.session_id
 AND first_task_sequence<=NEW.task_sequence AND last_task_sequence>=NEW.task_sequence
 ORDER BY first_task_sequence DESC LIMIT 1)
 WHERE event_id=NEW.event_id AND projection_block_start IS NULL AND {_NEXT};
 UPDATE task_projection_source_heads SET through_sequence=NEW.task_sequence WHERE {_SCOPE}
 AND through_sequence=NEW.task_sequence-1 AND EXISTS (SELECT 1 FROM session_events
 WHERE event_id=NEW.event_id AND projection_block_start IS NOT NULL);
"""


def initialize_projection_source_metadata(connection: sqlite3.Connection) -> None:
    """Install after Task positions. Main owns composition; never implicitly backfill."""
    for name, definition in (
        ("projection_handoff_id", "TEXT"),
        ("projection_peer_segment_id", "TEXT"),
        (
            "projection_metadata_ready",
            "INTEGER NOT NULL DEFAULT 0 CHECK(projection_metadata_ready IN (0,1))",
        ),
        ("projection_block_start", "INTEGER CHECK(projection_block_start>=0)"),
    ):
        ensure_column(connection, "session_events", name, definition)
    extraction = f"""UPDATE session_events SET projection_handoff_id=({_ID}),
      projection_peer_segment_id=({_PEER}),projection_metadata_ready=1
      WHERE event_id=NEW.event_id AND projection_metadata_ready=0;"""
    new_id = _ID.replace("payload", "NEW.payload").replace("event_type", "NEW.event_type")
    new_peer = _PEER.replace("payload", "NEW.payload").replace("event_type", "NEW.event_type")
    connection.executescript(
        SCHEMA
        + f"""
CREATE TRIGGER IF NOT EXISTS session_events_projection_input BEFORE INSERT ON session_events
WHEN NEW.projection_metadata_ready!=0 OR NEW.projection_handoff_id IS NOT NULL
 OR NEW.projection_peer_segment_id IS NOT NULL OR NEW.projection_block_start IS NOT NULL
BEGIN SELECT RAISE(ABORT,'projection metadata insertion must use source defaults'); END;
CREATE TRIGGER IF NOT EXISTS session_events_projection_insert AFTER INSERT ON session_events
BEGIN {extraction} END;
CREATE TRIGGER IF NOT EXISTS session_events_projection_assign
AFTER UPDATE OF task_id,task_sequence ON session_events
BEGIN {extraction}
END;
CREATE TRIGGER IF NOT EXISTS session_events_projection_build
AFTER UPDATE OF task_id,task_sequence ON session_events
WHEN NEW.task_id IS NOT NULL AND EXISTS (SELECT 1 FROM execution_segments
 WHERE session_id=NEW.session_id AND task_id=NEW.task_id)
BEGIN {_BUILD} END;
CREATE TRIGGER IF NOT EXISTS session_events_projection_fields
BEFORE UPDATE OF projection_handoff_id,projection_peer_segment_id,projection_metadata_ready
ON session_events WHEN NEW.projection_metadata_ready!=1 OR
 (OLD.projection_metadata_ready=1 AND
 (NEW.projection_handoff_id IS NOT OLD.projection_handoff_id OR
 NEW.projection_peer_segment_id IS NOT OLD.projection_peer_segment_id)) OR
 (OLD.projection_metadata_ready=0 AND (NEW.projection_handoff_id IS NOT ({new_id})
 OR NEW.projection_peer_segment_id IS NOT ({new_peer})))
BEGIN SELECT RAISE(ABORT,'projection metadata must match immutable source'); END;
CREATE TRIGGER IF NOT EXISTS session_events_projection_handoff
AFTER UPDATE OF projection_metadata_ready ON session_events
WHEN NEW.event_type IN ('session_handoff_committed','session_handoff_received')
 AND (NEW.projection_handoff_id IS NULL OR NEW.projection_peer_segment_id IS NULL
 OR NEW.projection_peer_segment_id=NEW.session_id)
BEGIN SELECT RAISE(ABORT,'invalid handoff metadata'); END;
CREATE TRIGGER IF NOT EXISTS session_events_projection_body
BEFORE UPDATE OF payload,actor,event_type ON session_events WHEN OLD.projection_metadata_ready=1
 AND (NEW.payload IS NOT OLD.payload OR NEW.actor IS NOT OLD.actor
 OR NEW.event_type IS NOT OLD.event_type)
BEGIN SELECT RAISE(ABORT,'projection metadata source is immutable'); END;
CREATE TRIGGER IF NOT EXISTS session_events_projection_coordinate
BEFORE UPDATE OF projection_block_start ON session_events
WHEN (OLD.projection_block_start IS NOT NULL
 AND NEW.projection_block_start IS NOT OLD.projection_block_start)
 OR NOT EXISTS (SELECT 1 FROM task_projection_blocks b JOIN agent_tasks t ON t.task_id=b.task_id
 WHERE b.deployment_namespace=t.namespace AND b.task_id=NEW.task_id
 AND b.segment_id=NEW.session_id AND b.first_task_sequence=NEW.projection_block_start
 AND NEW.task_sequence BETWEEN b.first_task_sequence AND b.last_task_sequence
 AND NEW.sequence=b.first_segment_sequence+NEW.task_sequence-b.first_task_sequence)
BEGIN SELECT RAISE(ABORT,'projection block conflicts with source'); END;
"""
    )
