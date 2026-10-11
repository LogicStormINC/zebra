"""Native append-only Task descriptor proof; not a cache of current permissions."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_TASK_SUMMARY_MIGRATION = Migration(
    version=89,
    name="coverage_task_admission_summary",
    statements=(
        """CREATE TABLE coverage_task_summary (
           deployment_namespace TEXT NOT NULL,session_id UUID NOT NULL,
           last_sequence BIGINT NOT NULL DEFAULT -1,origin JSONB,
           task_count BIGINT NOT NULL DEFAULT 0,invalidated BOOLEAN NOT NULL DEFAULT FALSE,
           PRIMARY KEY(deployment_namespace,session_id))""",
        """INSERT INTO coverage_task_summary(deployment_namespace,session_id,invalidated)
           SELECT deployment_namespace,session_id,TRUE FROM session_streams""",
        """CREATE FUNCTION guard_coverage_task_summary() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF pg_trigger_depth()<2 OR TG_OP IN ('DELETE','TRUNCATE') THEN
               RAISE EXCEPTION 'Task summaries are database maintained';
             END IF;
             IF TG_OP='UPDATE' AND (
               (NEW.deployment_namespace,NEW.session_id) IS DISTINCT FROM
               (OLD.deployment_namespace,OLD.session_id)
               OR (OLD.invalidated AND NOT NEW.invalidated)) THEN
               RAISE EXCEPTION 'Task summary identity/invalidation cannot reset';
             END IF;
             RETURN NEW;
           END $$""",
        """CREATE TRIGGER coverage_task_summary_guard BEFORE INSERT OR UPDATE OR DELETE
           ON coverage_task_summary FOR EACH ROW EXECUTE FUNCTION guard_coverage_task_summary()""",
        """CREATE TRIGGER coverage_task_summary_no_truncate BEFORE TRUNCATE
           ON coverage_task_summary FOR EACH STATEMENT
           EXECUTE FUNCTION guard_coverage_task_summary()""",
        """CREATE FUNCTION advance_coverage_task_summary() RETURNS trigger
           LANGUAGE plpgsql AS $$ DECLARE
             body JSONB;previous JSONB;scope JSONB;facts coverage_task_summary;
             dep TEXT;sid UUID;
           BEGIN
             IF TG_OP='TRUNCATE' THEN
               UPDATE coverage_task_summary SET invalidated=TRUE;
               RETURN NULL;
             END IF;
             IF TG_OP<>'INSERT' THEN previous=to_jsonb(OLD); END IF;
             IF TG_OP<>'DELETE' THEN body=to_jsonb(NEW); END IF;
             FOR scope IN SELECT DISTINCT jsonb_build_object(
               'deployment_namespace',value->>'deployment_namespace',
               'session_id',value->>'session_id') FROM unnest(ARRAY[previous,body]) s(value)
               WHERE value IS NOT NULL LOOP
               dep=scope->>'deployment_namespace';sid=(scope->>'session_id')::uuid;
               INSERT INTO coverage_task_summary(deployment_namespace,session_id)
                 VALUES(dep,sid) ON CONFLICT DO NOTHING;
               SELECT * INTO facts FROM coverage_task_summary WHERE
                 deployment_namespace=dep AND session_id=sid FOR UPDATE;
               IF facts.invalidated THEN CONTINUE; END IF;
               IF TG_OP<>'INSERT' OR (body->>'sequence')::bigint<>facts.last_sequence+1
                 OR (body->>'event_type'='task_prepared' AND (
                   body->'payload'->'coverage_admission' IS NULL
                   OR body->'payload'->'coverage_admission'='null'::jsonb
                   OR (facts.origin IS NOT NULL
                     AND facts.origin->'payload' IS DISTINCT FROM body->'payload'))) THEN
                 UPDATE coverage_task_summary SET invalidated=TRUE WHERE
                   deployment_namespace=dep AND session_id=sid;
                 CONTINUE;
               END IF;
               UPDATE coverage_task_summary SET last_sequence=(body->>'sequence')::bigint,
                 origin=CASE WHEN body->>'event_type'='task_prepared'
                   THEN coalesce(origin,body) ELSE origin END,
                 task_count=task_count+CASE WHEN body->>'event_type'='task_prepared'
                   THEN 1 ELSE 0 END WHERE deployment_namespace=dep AND session_id=sid;
             END LOOP;
             RETURN NULL;
           END $$""",
        """CREATE TRIGGER coverage_task_summary_events AFTER INSERT OR UPDATE OR DELETE
           ON session_events FOR EACH ROW EXECUTE FUNCTION advance_coverage_task_summary()""",
        """CREATE TRIGGER coverage_task_summary_events_truncate AFTER TRUNCATE
           ON session_events FOR EACH STATEMENT
           EXECUTE FUNCTION advance_coverage_task_summary()""",
    ),
)
