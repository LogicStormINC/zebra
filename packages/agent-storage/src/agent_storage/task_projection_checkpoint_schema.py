"""Append-only derived headers and keyed state; source Events remain authority."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_projection_heads (
    deployment_namespace TEXT NOT NULL,
    task_id TEXT NOT NULL,
    anchor_key TEXT NOT NULL,
    projector_version TEXT NOT NULL,
    through_sequence INTEGER NOT NULL DEFAULT -1 CHECK(through_sequence >= -1),
    last_event_id TEXT,
    latest_eligible_sequence INTEGER,
    terminal_sequence INTEGER,
    PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version),
    CHECK((through_sequence=-1)=(last_event_id IS NULL))
);
CREATE TABLE IF NOT EXISTS task_projection_frames (
    deployment_namespace TEXT NOT NULL, task_id TEXT NOT NULL,
    anchor_key TEXT NOT NULL, projector_version TEXT NOT NULL,
    task_sequence INTEGER NOT NULL CHECK(task_sequence >= 0),
    event_id TEXT NOT NULL, segment_id TEXT NOT NULL,
    segment_sequence INTEGER NOT NULL CHECK(segment_sequence >= 0),
    state_before_sequence INTEGER NOT NULL CHECK(state_before_sequence >= -1),
    frame_count INTEGER NOT NULL CHECK(frame_count BETWEEN 0 AND 4096),
    projected INTEGER NOT NULL CHECK(projected IN (0,1)),
    eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
    PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version,task_sequence),
    CHECK(state_before_sequence < task_sequence),
    CHECK(eligible <= projected), CHECK(projected=1 OR frame_count=0)
);
CREATE TABLE IF NOT EXISTS task_projection_scalars (
    deployment_namespace TEXT NOT NULL, task_id TEXT NOT NULL,
    anchor_key TEXT NOT NULL, projector_version TEXT NOT NULL,
    segment_id TEXT NOT NULL, task_sequence INTEGER NOT NULL CHECK(task_sequence >= 0),
    segment_sequence INTEGER NOT NULL CHECK(segment_sequence >= 0),
    started INTEGER NOT NULL CHECK(started IN (0,1)),
    turn_finished INTEGER NOT NULL CHECK(turn_finished IN (0,1)),
    PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version,segment_id,task_sequence)
);
CREATE TABLE IF NOT EXISTS task_projection_cells (
    deployment_namespace TEXT NOT NULL, task_id TEXT NOT NULL,
    anchor_key TEXT NOT NULL, projector_version TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    cell_kind TEXT NOT NULL CHECK(cell_kind IN (
        'text_message','text_ended','tool_call','interrupt','run_member','handoff')),
    cell_key TEXT NOT NULL, task_sequence INTEGER NOT NULL CHECK(task_sequence >= 0),
    value TEXT, byte_count INTEGER NOT NULL CHECK(byte_count>0),
    PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version,
                segment_id,cell_kind,cell_key,task_sequence)
);
"""
