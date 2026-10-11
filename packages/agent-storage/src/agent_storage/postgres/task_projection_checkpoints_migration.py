"""v64: append-only derived checkpoints; no foreign keys into source lock domains."""

from agent_storage.postgres.migration_types import Migration

TASK_PROJECTION_CHECKPOINTS_MIGRATION = Migration(
    version=64,
    name="task_projection_checkpoints",
    statements=(
        """CREATE TABLE task_projection_heads (
            deployment_namespace TEXT NOT NULL, task_id UUID NOT NULL,
            anchor_key TEXT NOT NULL, projector_version TEXT NOT NULL,
            through_sequence BIGINT NOT NULL DEFAULT -1 CHECK(through_sequence >= -1),
            last_event_id UUID,
            latest_eligible_sequence BIGINT, terminal_sequence BIGINT,
            PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version),
            CHECK((through_sequence=-1)=(last_event_id IS NULL)),
            CHECK(latest_eligible_sequence BETWEEN 0 AND through_sequence),
            CHECK(terminal_sequence BETWEEN 0 AND through_sequence),
            CHECK(anchor_key='' OR anchor_key ~
                '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
            CHECK(octet_length(projector_version) BETWEEN 1 AND 64),
            CHECK(octet_length(deployment_namespace) BETWEEN 1 AND 256)
        )""",
        """CREATE TABLE task_projection_frames (
            deployment_namespace TEXT NOT NULL, task_id UUID NOT NULL,
            anchor_key TEXT NOT NULL, projector_version TEXT NOT NULL,
            task_sequence BIGINT NOT NULL CHECK(task_sequence >= 0),
            event_id UUID NOT NULL, segment_id UUID NOT NULL,
            segment_sequence BIGINT NOT NULL CHECK(segment_sequence >= 0),
            state_before_sequence BIGINT NOT NULL CHECK(state_before_sequence >= -1),
            frame_count INTEGER NOT NULL CHECK(frame_count BETWEEN 0 AND 4096),
            projected BOOLEAN NOT NULL, eligible BOOLEAN NOT NULL,
            PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version,task_sequence),
            UNIQUE(deployment_namespace,task_id,anchor_key,projector_version,event_id),
            FOREIGN KEY(deployment_namespace,task_id,anchor_key,projector_version)
                REFERENCES task_projection_heads ON DELETE CASCADE,
            CHECK(state_before_sequence < task_sequence),
            CHECK(NOT eligible OR projected), CHECK(projected OR frame_count=0)
        )""",
        """CREATE TABLE task_projection_scalars (
            deployment_namespace TEXT NOT NULL, task_id UUID NOT NULL,
            anchor_key TEXT NOT NULL, projector_version TEXT NOT NULL,
            segment_id UUID NOT NULL, task_sequence BIGINT NOT NULL CHECK(task_sequence >= 0),
            segment_sequence BIGINT NOT NULL CHECK(segment_sequence >= 0),
            started BOOLEAN NOT NULL, turn_finished BOOLEAN NOT NULL,
            PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version,
                        segment_id,task_sequence),
            FOREIGN KEY(deployment_namespace,task_id,anchor_key,projector_version,task_sequence)
                REFERENCES task_projection_frames ON DELETE CASCADE
        )""",
        """CREATE TABLE task_projection_cells (
            deployment_namespace TEXT NOT NULL, task_id UUID NOT NULL,
            anchor_key TEXT NOT NULL, projector_version TEXT NOT NULL,
            segment_id UUID NOT NULL,
            cell_kind TEXT NOT NULL CHECK(cell_kind IN (
                'text_message','text_ended','tool_call','interrupt','run_member','handoff')),
            cell_key TEXT NOT NULL CHECK(octet_length(cell_key) BETWEEN 1 AND 1024),
            task_sequence BIGINT NOT NULL CHECK(task_sequence >= 0),
            value TEXT CHECK(value IS NULL OR octet_length(value) BETWEEN 1 AND 2048),
            byte_count BIGINT NOT NULL CHECK(byte_count=
                256+6*octet_length(cell_key)+6*COALESCE(octet_length(value),0)),
            PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version,
                        segment_id,cell_kind,cell_key,task_sequence),
            FOREIGN KEY(deployment_namespace,task_id,anchor_key,projector_version,task_sequence)
                REFERENCES task_projection_frames ON DELETE CASCADE,
            CHECK(cell_kind IN ('text_message','handoff') OR value IS NULL OR value='1')
        )""",
    ),
)
