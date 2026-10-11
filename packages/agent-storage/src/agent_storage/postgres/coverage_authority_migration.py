"""Native lineage mutation versions for already verified execution contexts."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_AUTHORITY_MIGRATION = Migration(
    version=90,
    name="coverage_authority_lineage_versions",
    statements=(
        """CREATE TABLE coverage_lineage_versions (
           deployment_namespace TEXT NOT NULL,session_id UUID NOT NULL,
           revision BIGINT NOT NULL DEFAULT 0 CHECK(revision>=0),
           PRIMARY KEY(deployment_namespace,session_id))""",
        """INSERT INTO coverage_lineage_versions(deployment_namespace,session_id)
           SELECT deployment_namespace,session_id FROM session_projections""",
        """CREATE INDEX coverage_authority_stop ON session_events(deployment_namespace,session_id)
           WHERE event_type IN ('session_cancelled','session_failed','session_completed')
             OR (event_type='session_command_accepted'
                 AND payload->>'kind' IN ('stop','cancel'))""",
        """CREATE INDEX coverage_lineage_received_root
           ON session_events(deployment_namespace,session_id)
           WHERE event_type='session_handoff_received'""",
        """CREATE FUNCTION guard_coverage_lineage_versions() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF pg_trigger_depth()<2 OR TG_OP IN ('DELETE','TRUNCATE') THEN
               RAISE EXCEPTION 'lineage versions are database maintained';
             END IF;
             IF TG_OP='UPDATE' AND ((NEW.deployment_namespace,NEW.session_id)
                 IS DISTINCT FROM (OLD.deployment_namespace,OLD.session_id)
                 OR NEW.revision<=OLD.revision) THEN
               RAISE EXCEPTION 'lineage version must advance';
             END IF;
             RETURN NEW;
           END $$""",
        """CREATE TRIGGER coverage_lineage_versions_guard BEFORE INSERT OR UPDATE OR DELETE
           ON coverage_lineage_versions FOR EACH ROW
           EXECUTE FUNCTION guard_coverage_lineage_versions()""",
        """CREATE TRIGGER coverage_lineage_versions_no_truncate BEFORE TRUNCATE
           ON coverage_lineage_versions FOR EACH STATEMENT
           EXECUTE FUNCTION guard_coverage_lineage_versions()""",
        """CREATE FUNCTION advance_coverage_lineage_versions() RETURNS trigger
           LANGUAGE plpgsql AS $$ DECLARE
             body JSONB;previous JSONB;dep TEXT;sid UUID;
           BEGIN
             IF TG_OP='TRUNCATE' THEN
               UPDATE coverage_lineage_versions SET revision=revision+1;
               RETURN NULL;
             END IF;
             IF TG_OP<>'INSERT' THEN previous=to_jsonb(OLD); END IF;
             IF TG_OP<>'DELETE' THEN body=to_jsonb(NEW); END IF;
             IF TG_TABLE_NAME='session_events' AND NOT (
                 coalesce(previous->>'event_type','') IN
                   ('session_handoff_received','session_handoff_committed') OR
                 coalesce(body->>'event_type','') IN
                   ('session_handoff_received','session_handoff_committed')) THEN
               RETURN NULL;
             END IF;
             IF TG_TABLE_NAME='session_projections' AND TG_OP='UPDATE' AND
                 (body->>'deployment_namespace',body->>'session_id',body->>'namespace_id')
                 IS NOT DISTINCT FROM (previous->>'deployment_namespace',
                   previous->>'session_id',previous->>'namespace_id') THEN
               RETURN NULL;
             END IF;
             FOR dep,sid IN WITH scopes AS (
               SELECT value->>'deployment_namespace' AS d,ARRAY[
                 (value->>'session_id')::uuid,(value->>'task_id')::uuid,
                 nullif(value->'payload'->>'root_session_id','')::uuid,
                 nullif(value->'payload'->>'parent_session_id','')::uuid,
                 nullif(value->'payload'->>'target_session_id','')::uuid] AS sids
               FROM unnest(ARRAY[previous,body]) s(value) WHERE value IS NOT NULL)
               SELECT DISTINCT d,id FROM scopes CROSS JOIN LATERAL (
                 SELECT unnest(sids) AS id UNION ALL
                 SELECT nullif(payload->>'root_session_id','')::uuid FROM session_events
                   WHERE deployment_namespace=d AND session_id=ANY(sids)
                     AND event_type='session_handoff_received'
               ) candidates WHERE id IS NOT NULL ORDER BY d,id LOOP
                 INSERT INTO coverage_lineage_versions(deployment_namespace,session_id)
                   VALUES(dep,sid) ON CONFLICT(deployment_namespace,session_id)
                   DO UPDATE SET revision=coverage_lineage_versions.revision+1;
             END LOOP;
             RETURN NULL;
           END $$""",
        """CREATE TRIGGER coverage_lineage_events AFTER INSERT OR UPDATE OR DELETE
           ON session_events FOR EACH ROW EXECUTE FUNCTION advance_coverage_lineage_versions()""",
        """CREATE TRIGGER coverage_lineage_projections AFTER INSERT OR UPDATE OR DELETE
           ON session_projections FOR EACH ROW
           EXECUTE FUNCTION advance_coverage_lineage_versions()""",
        """CREATE TRIGGER coverage_lineage_bindings AFTER INSERT OR UPDATE OR DELETE
           ON task_binding_snapshots FOR EACH ROW
           EXECUTE FUNCTION advance_coverage_lineage_versions()""",
        """CREATE TRIGGER coverage_lineage_events_truncate AFTER TRUNCATE ON session_events
           FOR EACH STATEMENT EXECUTE FUNCTION advance_coverage_lineage_versions()""",
        """CREATE TRIGGER coverage_lineage_projections_truncate AFTER TRUNCATE
           ON session_projections FOR EACH STATEMENT
           EXECUTE FUNCTION advance_coverage_lineage_versions()""",
        """CREATE TRIGGER coverage_lineage_bindings_truncate AFTER TRUNCATE
           ON task_binding_snapshots FOR EACH STATEMENT
           EXECUTE FUNCTION advance_coverage_lineage_versions()""",
    ),
)
