"""v87: transactional mutation revisions replace repeated receipt history scans."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_MODEL_REVISION_MIGRATION = Migration(
    version=87,
    name="coverage_model_revision_root",
    statements=(
        """CREATE TABLE coverage_model_revisions (
           deployment_namespace TEXT NOT NULL, namespace TEXT NOT NULL, run_id TEXT NOT NULL,
           generation UUID NOT NULL DEFAULT gen_random_uuid(),
           revision BIGINT NOT NULL CHECK (revision>0),
           PRIMARY KEY (deployment_namespace,namespace,run_id))""",
        """INSERT INTO coverage_model_revisions
           (deployment_namespace,namespace,run_id,revision)
           SELECT deployment_namespace,namespace,run_id,1 FROM (
             SELECT deployment_namespace,namespace,run_id FROM coverage_model_ledger
             UNION SELECT deployment_namespace,namespace,run_id FROM coverage_model_calls
             UNION SELECT deployment_namespace,namespace,run_id FROM coverage_model_events
             UNION SELECT deployment_namespace,payload->>'namespace',payload->>'run_id'
               FROM session_events WHERE event_type IN ('coverage_model_budget_initialized',
                 'coverage_model_call_reserved','coverage_model_usage_recorded')
           ) scopes WHERE namespace IS NOT NULL AND run_id IS NOT NULL""",
        """CREATE FUNCTION guard_coverage_model_revision() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF pg_trigger_depth()<2 OR TG_OP IN ('DELETE','TRUNCATE') THEN
               RAISE EXCEPTION 'MODEL revision roots are database maintained';
             END IF;
             IF TG_OP='UPDATE' AND (NEW.generation<>OLD.generation
                 OR NEW.revision<>OLD.revision+1
                 OR (NEW.deployment_namespace,NEW.namespace,NEW.run_id)
                    IS DISTINCT FROM (OLD.deployment_namespace,OLD.namespace,OLD.run_id)) THEN
               RAISE EXCEPTION 'MODEL revision roots must advance exactly once';
             END IF;
             RETURN NEW;
           END $$""",
        """CREATE TRIGGER coverage_model_revision_guard BEFORE INSERT OR UPDATE OR DELETE
           ON coverage_model_revisions FOR EACH ROW
           EXECUTE FUNCTION guard_coverage_model_revision()""",
        """CREATE TRIGGER coverage_model_revision_no_truncate BEFORE TRUNCATE
           ON coverage_model_revisions FOR EACH STATEMENT
           EXECUTE FUNCTION guard_coverage_model_revision()""",
        """CREATE FUNCTION advance_coverage_model_revision() RETURNS trigger
           LANGUAGE plpgsql AS $$ DECLARE
             body JSONB; previous JSONB; scope JSONB; scopes JSONB[]; seen JSONB;
           BEGIN
             IF TG_OP='TRUNCATE' THEN
               -- ponytail: administrative truncate invalidates every root;
               -- normal row mutations touch only their exact opaque scope.
               UPDATE coverage_model_revisions SET revision=revision+1;
               RETURN NULL;
             END IF;
             IF TG_OP<>'INSERT' THEN previous=to_jsonb(OLD); END IF;
             IF TG_OP<>'DELETE' THEN body=to_jsonb(NEW); END IF;
             scopes=ARRAY[previous,body];
             FOR scope IN SELECT DISTINCT value FROM unnest(scopes) AS s(value)
               WHERE value IS NOT NULL LOOP
               IF TG_TABLE_NAME='session_events' THEN
                 IF scope->>'event_type' NOT IN ('coverage_model_budget_initialized',
                   'coverage_model_call_reserved','coverage_model_usage_recorded') THEN
                   CONTINUE;
                 END IF;
                 scope=jsonb_build_object('deployment_namespace',scope->>'deployment_namespace',
                   'namespace',scope->'payload'->>'namespace','run_id',scope->'payload'->>'run_id');
               ELSE
                 scope=jsonb_build_object('deployment_namespace',scope->>'deployment_namespace',
                   'namespace',scope->>'namespace','run_id',scope->>'run_id');
               END IF;
               IF scope->>'namespace' IS NULL OR scope->>'run_id' IS NULL THEN CONTINUE; END IF;
               IF scope=seen THEN CONTINUE; END IF;
               seen=scope;
               INSERT INTO coverage_model_revisions
                 (deployment_namespace,namespace,run_id,revision) VALUES
                 (scope->>'deployment_namespace',scope->>'namespace',scope->>'run_id',1)
               ON CONFLICT (deployment_namespace,namespace,run_id)
                 DO UPDATE SET revision=coverage_model_revisions.revision+1;
             END LOOP;
             RETURN NULL;
           END $$""",
        *tuple(
            f"""CREATE TRIGGER coverage_model_revision_{table}
                AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW
                EXECUTE FUNCTION advance_coverage_model_revision()"""
            for table in ("session_events", "coverage_model_events",
                          "coverage_model_calls", "coverage_model_ledger")
        ),
        *tuple(
            f"""CREATE TRIGGER coverage_model_revision_truncate_{table}
                AFTER TRUNCATE ON {table} FOR EACH STATEMENT
                EXECUTE FUNCTION advance_coverage_model_revision()"""
            for table in ("session_events", "coverage_model_events",
                          "coverage_model_calls", "coverage_model_ledger")
        ),
    ),
)
