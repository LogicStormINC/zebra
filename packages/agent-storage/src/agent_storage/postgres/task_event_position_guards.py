"""Native source/index guards; no caller-specific insertion escape hatch."""

TASK_POSITION_GUARDS = (
    """CREATE OR REPLACE FUNCTION guard_task_event_source() RETURNS trigger AS $$
       DECLARE member UUID; task RECORD; tail BIGINT;
       BEGIN
         IF TG_OP='INSERT' THEN
           IF NEW.task_id IS NOT NULL OR NEW.task_sequence IS NOT NULL THEN
             RAISE EXCEPTION 'positioned Event insertion requires explicit import'
               USING ERRCODE='55000';
           END IF;
           SELECT sequence INTO tail FROM session_events
             WHERE deployment_namespace=NEW.deployment_namespace AND session_id=NEW.session_id
             ORDER BY sequence DESC LIMIT 1;
           IF NEW.sequence<>COALESCE(tail+1,0) THEN
             RAISE EXCEPTION 'source Event sequence must be contiguous' USING ERRCODE='55000';
           END IF;
           RETURN NEW;
         END IF;
         IF TG_OP='DELETE' THEN
           SELECT task_id INTO member FROM execution_segments
             WHERE deployment_namespace=OLD.deployment_namespace AND session_id=OLD.session_id;
           IF OLD.task_id IS NOT NULL OR member IS NOT NULL THEN
             -- ponytail: an explicit owner-only namespace purge, after Task FK
             -- decommission. Missing membership alone is never authorization.
             IF member IS NULL
                AND NOT EXISTS (SELECT 1 FROM agent_tasks
                  WHERE deployment_namespace=OLD.deployment_namespace AND task_id=OLD.task_id)
                AND current_setting('zebra.task_source_cleanup_namespace',true)
                    =OLD.deployment_namespace
                AND pg_has_role(current_user,(SELECT datdba FROM pg_database
                    WHERE datname=current_database()),'MEMBER') THEN
               RETURN OLD;
             END IF;
             RAISE EXCEPTION 'canonical Task source Events are immutable' USING ERRCODE='55000';
           END IF;
           RETURN OLD;
         END IF;
         IF (NEW.deployment_namespace,NEW.event_id,NEW.session_id,NEW.sequence)
             IS DISTINCT FROM
            (OLD.deployment_namespace,OLD.event_id,OLD.session_id,OLD.sequence)
            OR (OLD.task_id IS NOT NULL AND (NEW.task_id,NEW.task_sequence)
                IS DISTINCT FROM (OLD.task_id,OLD.task_sequence)) THEN
           RAISE EXCEPTION 'canonical Task Event positions are immutable' USING ERRCODE='55000';
         END IF;
         IF OLD.task_id IS NULL AND NEW.task_id IS NOT NULL THEN
           SELECT task_id INTO member FROM execution_segments
             WHERE deployment_namespace=NEW.deployment_namespace AND session_id=NEW.session_id;
           IF member IS NOT NULL THEN
             IF NEW.task_id<>member THEN
               RAISE EXCEPTION 'source Event belongs to another Task' USING ERRCODE='55000';
             END IF;
             -- UPDATE already owns a source row: never wait on Task61 in reverse order.
             IF NOT pg_try_advisory_xact_lock(
                 hashtextextended(NEW.deployment_namespace || ':' || member::text,61)) THEN
               RAISE EXCEPTION 'Task position mutation is busy' USING ERRCODE='55000';
             END IF;
             SELECT event_position_state,next_event_sequence INTO task FROM agent_tasks
               WHERE deployment_namespace=NEW.deployment_namespace AND task_id=member;
             IF NOT FOUND OR (task.event_position_state='ready'
                 AND NEW.task_sequence IS DISTINCT FROM task.next_event_sequence-1) THEN
               RAISE EXCEPTION 'source Event position was not allocated' USING ERRCODE='55000';
             END IF;
           END IF;
         END IF;
         RETURN NEW;
       END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS session_events_task_positions_immutable ON session_events",
    """CREATE TRIGGER session_events_task_positions_immutable
       BEFORE UPDATE ON session_events FOR EACH ROW EXECUTE FUNCTION guard_task_event_source()""",
    "DROP TRIGGER IF EXISTS session_events_source_append_order ON session_events",
    """CREATE TRIGGER session_events_source_append_order
       BEFORE INSERT ON session_events FOR EACH ROW EXECUTE FUNCTION guard_task_event_source()""",
    # Recreate, rather than IF NOT EXISTS: upgrade the older membership-only guard.
    "DROP TRIGGER IF EXISTS session_events_task_source_delete ON session_events",
    """CREATE TRIGGER session_events_task_source_delete
       BEFORE DELETE ON session_events FOR EACH ROW EXECUTE FUNCTION guard_task_event_source()""",
    """CREATE OR REPLACE FUNCTION guard_task_event_reservation() RETURNS trigger AS $$
       DECLARE bound RECORD; phase TEXT;
       BEGIN
         FOR bound IN SELECT DISTINCT namespace,task_id FROM
             (VALUES (NEW.deployment_namespace,NEW.task_id),
                     (OLD.deployment_namespace,OLD.task_id)) AS targets(namespace,task_id)
             WHERE task_id IS NOT NULL ORDER BY namespace,task_id LOOP
           -- Native index UPDATE/DELETE may already own a row. Fail busy instead
           -- of creating index-row -> Task61 -> source/index-row deadlocks.
           IF NOT pg_try_advisory_xact_lock(
               hashtextextended(bound.namespace || ':' || bound.task_id::text,61)) THEN
             RAISE EXCEPTION 'Task position mutation is busy' USING ERRCODE='55000';
           END IF;
           SELECT event_position_state INTO phase FROM agent_tasks
             WHERE deployment_namespace=bound.namespace AND task_id=bound.task_id;
           IF phase IN ('validating','assigning') THEN
             IF TG_OP<>'INSERT' OR NOT EXISTS (SELECT 1 FROM session_events
                 WHERE deployment_namespace=NEW.deployment_namespace AND event_id=NEW.event_id
                   AND (task_id,task_sequence,session_id,sequence)=
                       (NEW.task_id,NEW.task_sequence,NEW.segment_id,NEW.segment_sequence)) THEN
               RAISE EXCEPTION 'legacy Task reservations are frozen during adoption'
                 USING ERRCODE='55000';
             END IF;
           END IF;
         END LOOP;
         IF TG_OP='DELETE' THEN RETURN OLD; END IF;
         RETURN NEW;
       END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS task_event_reservation_guard ON task_event_index",
    """CREATE TRIGGER task_event_reservation_guard BEFORE INSERT OR UPDATE OR DELETE
       ON task_event_index FOR EACH ROW EXECUTE FUNCTION guard_task_event_reservation()""",
)

# Additive only: TASK_POSITION_GUARDS is embedded in released Migration 61.
TASK_EVENT_BUSINESS_GUARDS = (
    """CREATE FUNCTION guard_task_event_business() RETURNS trigger AS $$ BEGIN
       IF (OLD.task_id IS NOT NULL OR NEW.task_id IS NOT NULL) AND
          (NEW.payload::text,NEW.actor,NEW.created_at,NEW.causation_id,NEW.correlation_id,
           NEW.idempotency_key,NEW.policy_version,NEW.model_profile,NEW.event_type)
          IS DISTINCT FROM
          (OLD.payload::text,OLD.actor,OLD.created_at,OLD.causation_id,OLD.correlation_id,
           OLD.idempotency_key,OLD.policy_version,OLD.model_profile,OLD.event_type) THEN
         RAISE EXCEPTION 'canonical Task Event business fields are immutable'
           USING ERRCODE='55000';
       END IF;
       RETURN NEW; END; $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER session_events_task_business_immutable
       BEFORE UPDATE OF payload,actor,created_at,causation_id,correlation_id,idempotency_key,
         policy_version,model_profile,event_type ON session_events
       FOR EACH ROW EXECUTE FUNCTION guard_task_event_business()""",
)
