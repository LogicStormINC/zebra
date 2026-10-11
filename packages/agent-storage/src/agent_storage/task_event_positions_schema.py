"""SQLite guards for immutable source positions and resumable adoption."""

POSITION_SCHEMA = """
CREATE UNIQUE INDEX IF NOT EXISTS session_events_task_positions
ON session_events(task_id,task_sequence) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS session_events_unpositioned
ON session_events(session_id,sequence) WHERE task_id IS NULL;
CREATE INDEX IF NOT EXISTS execution_segments_position_pending
ON execution_segments(task_id,segment_index) WHERE event_position_source_ready=0;
CREATE TRIGGER IF NOT EXISTS session_events_task_position_pair_insert
BEFORE INSERT ON session_events
WHEN (NEW.task_id IS NULL) != (NEW.task_sequence IS NULL)
BEGIN SELECT RAISE(ABORT,'Task Event coordinates must be paired'); END;
CREATE TRIGGER IF NOT EXISTS session_events_source_append_order
BEFORE INSERT ON session_events
WHEN NEW.sequence != COALESCE((SELECT MAX(sequence)+1 FROM session_events
  WHERE session_id=NEW.session_id),0)
BEGIN SELECT RAISE(ABORT,'source Event sequence must be contiguous'); END;
CREATE TRIGGER IF NOT EXISTS session_events_prepositioned_insert
BEFORE INSERT ON session_events WHEN NEW.task_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'positioned Event insertion requires explicit import'); END;
CREATE TRIGGER IF NOT EXISTS session_events_task_positions_immutable
BEFORE UPDATE ON session_events
WHEN NEW.event_id IS NOT OLD.event_id OR NEW.session_id IS NOT OLD.session_id
  OR NEW.sequence IS NOT OLD.sequence
  OR (NEW.task_id IS NULL) != (NEW.task_sequence IS NULL)
  OR (OLD.task_id IS NOT NULL AND
      (NEW.task_id IS NOT OLD.task_id OR NEW.task_sequence IS NOT OLD.task_sequence))
BEGIN SELECT RAISE(ABORT,'canonical Task Event positions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS session_events_task_business_immutable
BEFORE UPDATE OF payload,actor,created_at,causation_id,correlation_id,idempotency_key,
  policy_version,model_profile,event_type ON session_events
WHEN (OLD.task_id IS NOT NULL OR NEW.task_id IS NOT NULL) AND (
  NEW.payload IS NOT OLD.payload OR NEW.actor IS NOT OLD.actor
  OR NEW.created_at IS NOT OLD.created_at OR NEW.causation_id IS NOT OLD.causation_id
  OR NEW.correlation_id IS NOT OLD.correlation_id
  OR NEW.idempotency_key IS NOT OLD.idempotency_key
  OR NEW.policy_version IS NOT OLD.policy_version
  OR NEW.model_profile IS NOT OLD.model_profile OR NEW.event_type IS NOT OLD.event_type)
BEGIN SELECT RAISE(ABORT,'canonical Task Event business fields are immutable'); END;
CREATE TRIGGER IF NOT EXISTS session_events_task_assignment_guard
BEFORE UPDATE ON session_events
WHEN OLD.task_id IS NULL AND NEW.task_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM execution_segments WHERE session_id=NEW.session_id)
BEGIN
  SELECT CASE WHEN NEW.task_id IS NOT (SELECT task_id FROM execution_segments
    WHERE session_id=NEW.session_id)
    THEN RAISE(ABORT,'source Event belongs to another Task') END;
  SELECT CASE WHEN (SELECT event_position_state FROM agent_tasks WHERE task_id=NEW.task_id)
    = 'ready' AND NEW.task_sequence IS NOT
      (SELECT next_event_sequence-1 FROM agent_tasks WHERE task_id=NEW.task_id)
    THEN RAISE(ABORT,'source Event position was not allocated') END;
END;
DROP TRIGGER IF EXISTS session_events_task_source_delete;
CREATE TRIGGER session_events_task_source_delete
BEFORE DELETE ON session_events
WHEN OLD.task_id IS NOT NULL
  OR EXISTS (SELECT 1 FROM execution_segments WHERE session_id=OLD.session_id)
BEGIN SELECT RAISE(ABORT,'canonical Task source Events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS task_event_reservation_update
BEFORE UPDATE ON task_event_index
WHEN EXISTS (SELECT 1 FROM agent_tasks WHERE task_id IN (OLD.task_id,NEW.task_id)
  AND event_position_state IN ('validating','assigning'))
BEGIN SELECT RAISE(ABORT,'legacy Task reservations are frozen during adoption'); END;
CREATE TRIGGER IF NOT EXISTS task_event_reservation_delete
BEFORE DELETE ON task_event_index
WHEN EXISTS (SELECT 1 FROM agent_tasks WHERE task_id=OLD.task_id
  AND event_position_state IN ('validating','assigning'))
BEGIN SELECT RAISE(ABORT,'legacy Task reservations are frozen during adoption'); END;
CREATE TRIGGER IF NOT EXISTS task_event_reservation_insert
BEFORE INSERT ON task_event_index
WHEN EXISTS (SELECT 1 FROM agent_tasks WHERE task_id=NEW.task_id
  AND event_position_state IN ('validating','assigning'))
  AND NOT EXISTS (SELECT 1 FROM session_events WHERE event_id=NEW.event_id
    AND task_id=NEW.task_id AND task_sequence=NEW.task_sequence
    AND session_id=NEW.segment_id AND sequence=NEW.segment_sequence)
BEGIN SELECT RAISE(ABORT,'legacy Task reservations are frozen during adoption'); END;
DROP TRIGGER IF EXISTS session_events_allocate_task_position;
CREATE TRIGGER session_events_allocate_task_position
AFTER INSERT ON session_events
WHEN EXISTS (SELECT 1 FROM execution_segments WHERE session_id=NEW.session_id)
BEGIN
  SELECT CASE WHEN (SELECT event_position_state FROM agent_tasks
    WHERE task_id=(SELECT task_id FROM execution_segments WHERE session_id=NEW.session_id))
    != 'ready' THEN RAISE(ABORT,'Task Event positions require explicit backfill') END;
  UPDATE agent_tasks SET next_event_sequence=next_event_sequence+1
    WHERE task_id=(SELECT task_id FROM execution_segments WHERE session_id=NEW.session_id);
  UPDATE session_events SET
    task_id=(SELECT task_id FROM execution_segments WHERE session_id=NEW.session_id),
    task_sequence=(SELECT next_event_sequence-1 FROM agent_tasks
      WHERE task_id=(SELECT task_id FROM execution_segments WHERE session_id=NEW.session_id))
    WHERE event_id=NEW.event_id;
  UPDATE execution_segments SET event_position_source_cursor=NEW.sequence
    WHERE session_id=NEW.session_id;
  INSERT INTO task_event_index (task_id,task_sequence,event_id,segment_id,segment_sequence)
    SELECT task_id,task_sequence,event_id,session_id,sequence
    FROM session_events WHERE event_id=NEW.event_id;
END;
"""
