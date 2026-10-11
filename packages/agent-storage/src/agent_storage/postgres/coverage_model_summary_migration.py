"""v88: exact fresh-run MODEL facts maintained by native mutation transitions."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_MODEL_SUMMARY_MIGRATION = Migration(
    version=88,
    name="coverage_model_incremental_summary",
    statements=(
        """CREATE TABLE coverage_model_summary (
           deployment_namespace TEXT NOT NULL,namespace TEXT NOT NULL,run_id TEXT NOT NULL,
           session_id UUID,policy JSONB,invalidated BOOLEAN NOT NULL DEFAULT FALSE,
           initialized BIGINT NOT NULL DEFAULT 0,reserved BIGINT NOT NULL DEFAULT 0,
           receipts BIGINT NOT NULL DEFAULT 0,witnesses BIGINT NOT NULL DEFAULT 0,
           calls BIGINT NOT NULL DEFAULT 0,charged_tokens BIGINT NOT NULL DEFAULT 0,
           unresolved BIGINT NOT NULL DEFAULT 0,
           PRIMARY KEY (deployment_namespace,namespace,run_id))""",
        # Existing history is never upgraded from an unchecked projection.
        """INSERT INTO coverage_model_summary
           (deployment_namespace,namespace,run_id,invalidated)
           SELECT deployment_namespace,namespace,run_id,TRUE FROM coverage_model_revisions""",
        """CREATE FUNCTION guard_coverage_model_summary() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF pg_trigger_depth()<2 OR TG_OP IN ('DELETE','TRUNCATE') THEN
               RAISE EXCEPTION 'MODEL summaries are database maintained';
             END IF;
             IF TG_OP='UPDATE' AND (
               (NEW.deployment_namespace,NEW.namespace,NEW.run_id) IS DISTINCT FROM
               (OLD.deployment_namespace,OLD.namespace,OLD.run_id)
               OR (OLD.invalidated AND NOT NEW.invalidated)) THEN
               RAISE EXCEPTION 'MODEL summary identity/invalidation cannot reset';
             END IF;
             RETURN NEW;
           END $$""",
        """CREATE TRIGGER coverage_model_summary_guard BEFORE INSERT OR UPDATE OR DELETE
           ON coverage_model_summary FOR EACH ROW
           EXECUTE FUNCTION guard_coverage_model_summary()""",
        """CREATE TRIGGER coverage_model_summary_no_truncate BEFORE TRUNCATE
           ON coverage_model_summary FOR EACH STATEMENT
           EXECUTE FUNCTION guard_coverage_model_summary()""",
        """CREATE FUNCTION advance_coverage_model_summary() RETURNS trigger
           LANGUAGE plpgsql AS $$ DECLARE
             body JSONB;previous JSONB;scope JSONB;seen JSONB;facts coverage_model_summary;
             dep TEXT;ns TEXT;run TEXT;source JSONB;sid UUID;valid BOOLEAN;
           BEGIN
             IF TG_OP='TRUNCATE' THEN
               UPDATE coverage_model_summary SET invalidated=TRUE;
               RETURN NULL;
             END IF;
             IF TG_OP<>'INSERT' THEN previous=to_jsonb(OLD); END IF;
             IF TG_OP<>'DELETE' THEN body=to_jsonb(NEW); END IF;
             FOR scope IN SELECT DISTINCT value FROM unnest(ARRAY[previous,body]) s(value)
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
               dep=scope->>'deployment_namespace';ns=scope->>'namespace';run=scope->>'run_id';
               IF ns IS NULL OR run IS NULL OR scope=seen THEN CONTINUE; END IF;
               seen=scope;
               INSERT INTO coverage_model_summary (deployment_namespace,namespace,run_id)
                 VALUES(dep,ns,run) ON CONFLICT DO NOTHING;
               SELECT * INTO facts FROM coverage_model_summary WHERE
                 deployment_namespace=dep AND namespace=ns AND run_id=run FOR UPDATE;
               IF facts.invalidated THEN CONTINUE; END IF;
               -- Only append, first settlement and matching ledger updates are normal.
               IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND TG_TABLE_NAME NOT IN
                   ('coverage_model_calls','coverage_model_ledger'))
                   OR (previous IS NOT NULL AND
                     (previous->>'deployment_namespace',previous->>'namespace',previous->>'run_id')
                     IS DISTINCT FROM (dep,ns,run))
                   OR (body IS NOT NULL AND TG_TABLE_NAME<>'session_events' AND
                     (body->>'deployment_namespace',body->>'namespace',body->>'run_id')
                     IS DISTINCT FROM (dep,ns,run)) THEN
                 UPDATE coverage_model_summary SET invalidated=TRUE WHERE
                   deployment_namespace=dep AND namespace=ns AND run_id=run;
                 CONTINUE;
               END IF;
               valid=FALSE;
               IF TG_TABLE_NAME='session_events' THEN
                 sid=(body->>'session_id')::uuid;
                 valid=facts.session_id IS NULL OR facts.session_id=sid;
                 IF valid THEN
                   UPDATE coverage_model_summary SET session_id=sid,
                     policy=CASE WHEN body->>'event_type'='coverage_model_budget_initialized'
                       THEN body->'payload'->'policy' ELSE policy END,
                     initialized=initialized+CASE WHEN body->>'event_type'=
                       'coverage_model_budget_initialized' THEN 1 ELSE 0 END,
                     reserved=reserved+CASE WHEN body->>'event_type'=
                       'coverage_model_call_reserved' THEN 1 ELSE 0 END,
                     receipts=receipts+CASE WHEN body->>'event_type'=
                       'coverage_model_usage_recorded' THEN 1 ELSE 0 END
                     WHERE deployment_namespace=dep AND namespace=ns AND run_id=run;
                 END IF;
               ELSIF TG_TABLE_NAME='coverage_model_events' THEN
                 SELECT to_jsonb(e) INTO source FROM session_events e WHERE
                   deployment_namespace=dep AND session_id=facts.session_id
                   AND sequence=(body->>'sequence')::bigint;
                 valid=source IS NOT NULL AND source=body->'source_row'
                   AND source->'payload'->>'namespace'=ns AND source->'payload'->>'run_id'=run
                   AND source->>'event_type' IN ('coverage_model_budget_initialized',
                     'coverage_model_call_reserved','coverage_model_usage_recorded');
                 IF valid THEN
                   UPDATE coverage_model_summary SET witnesses=witnesses+1 WHERE
                     deployment_namespace=dep AND namespace=ns AND run_id=run;
                 END IF;
               ELSIF TG_TABLE_NAME='coverage_model_calls' THEN
                 SELECT to_jsonb(e) INTO source FROM session_events e WHERE
                   deployment_namespace=dep AND session_id=facts.session_id
                   AND sequence=(body->>'reserved_sequence')::bigint;
                 valid=source IS NOT NULL AND source->>'event_type'='coverage_model_call_reserved'
                   AND source->'payload'->>'namespace'=ns AND source->'payload'->>'run_id'=run
                   AND source->'payload'->'reservation'=body->'reservation'
                   AND body->'reservation'->>'reservation_key'=body->>'reservation_key';
                 IF TG_OP='INSERT' THEN
                   valid=valid AND body->'receipt'='null'::jsonb
                     AND body->'receipt_sequence'='null'::jsonb;
                   IF valid THEN
                     UPDATE coverage_model_summary SET calls=calls+1,unresolved=unresolved+1,
                       charged_tokens=charged_tokens+(body->'reservation'->>'token_bound')::bigint
                       WHERE deployment_namespace=dep AND namespace=ns AND run_id=run;
                   END IF;
                 ELSE
                   valid=valid AND (previous-'receipt'-'receipt_sequence')=
                     (body-'receipt'-'receipt_sequence') AND previous->'receipt'='null'::jsonb
                     AND previous->'receipt_sequence'='null'::jsonb
                     AND body->'receipt'<>'null'::jsonb
                     AND body->'receipt'->'reservation'=body->'reservation';
                   SELECT to_jsonb(e) INTO source FROM session_events e WHERE
                     deployment_namespace=dep AND session_id=facts.session_id
                     AND sequence=(body->>'receipt_sequence')::bigint;
                   valid=valid AND source IS NOT NULL
                     AND source->>'event_type'='coverage_model_usage_recorded'
                     AND source->'payload'->>'namespace'=ns AND source->'payload'->>'run_id'=run
                     AND source->'payload'->'receipt'=body->'receipt';
                   IF valid THEN
                     UPDATE coverage_model_summary SET unresolved=unresolved-1,
                       charged_tokens=charged_tokens-(body->'reservation'->>'token_bound')::bigint
                         +(body->'receipt'->>'total_tokens')::bigint
                       WHERE deployment_namespace=dep AND namespace=ns AND run_id=run;
                   END IF;
                 END IF;
               ELSE
                 valid=body->'policy'=facts.policy
                   AND (body->>'calls')::bigint=facts.calls
                   AND (body->>'charged_tokens')::bigint=facts.charged_tokens
                   AND (body->>'unresolved')::bigint=facts.unresolved;
               END IF;
               IF valid IS DISTINCT FROM TRUE THEN
                 UPDATE coverage_model_summary SET invalidated=TRUE WHERE
                   deployment_namespace=dep AND namespace=ns AND run_id=run;
               END IF;
             END LOOP;
             RETURN NULL;
           END $$""",
        *tuple(
            f"""CREATE TRIGGER coverage_model_summary_{table}
                AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW
                EXECUTE FUNCTION advance_coverage_model_summary()"""
            for table in ("session_events", "coverage_model_events",
                          "coverage_model_calls", "coverage_model_ledger")
        ),
        *tuple(
            f"""CREATE TRIGGER coverage_model_summary_truncate_{table}
                AFTER TRUNCATE ON {table} FOR EACH STATEMENT
                EXECUTE FUNCTION advance_coverage_model_summary()"""
            for table in ("session_events", "coverage_model_events",
                          "coverage_model_calls", "coverage_model_ledger")
        ),
    ),
)
