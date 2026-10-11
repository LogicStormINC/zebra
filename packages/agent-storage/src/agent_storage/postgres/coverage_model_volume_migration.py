"""v91: extend the exact native MODEL root with incremental original-volume facts."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_MODEL_VOLUME_MIGRATION = Migration(
    version=91,
    name="coverage_model_incremental_volume",
    statements=(
        # Existing summaries deliberately keep volume_ready=false: no history backfill.
        """ALTER TABLE coverage_model_summary
           ADD COLUMN volume_ready BOOLEAN NOT NULL DEFAULT FALSE,
           ADD COLUMN source_bytes BIGINT NOT NULL DEFAULT 0,
           ADD COLUMN original_bytes BIGINT NOT NULL DEFAULT 0,
           ADD COLUMN original_count BIGINT NOT NULL DEFAULT 0,
           ADD COLUMN volume_watermark BIGINT NOT NULL DEFAULT 0""",
        """CREATE INDEX coverage_model_checkpoint_ref ON coverage_model_calls
           (deployment_namespace, ((receipt->>'checkpoint_ref')))
           WHERE receipt IS NOT NULL""",
        """CREATE FUNCTION advance_coverage_model_volume() RETURNS trigger
           LANGUAGE plpgsql AS $$ DECLARE dep TEXT;ns TEXT;run TEXT;size BIGINT;
           BEGIN
             dep=NEW.deployment_namespace;
             IF TG_TABLE_NAME='session_events' THEN
               IF NEW.event_type NOT IN ('coverage_model_budget_initialized',
                 'coverage_model_call_reserved','coverage_model_usage_recorded') THEN
                 RETURN NULL;
               END IF;
               ns=NEW.payload->>'namespace';run=NEW.payload->>'run_id';
               UPDATE coverage_model_summary SET
                 volume_ready=volume_ready OR NEW.event_type='coverage_model_budget_initialized',
                 source_bytes=source_bytes+octet_length(to_jsonb(NEW)::text),
                 volume_watermark=greatest(volume_watermark,NEW.sequence)
                 WHERE deployment_namespace=dep AND namespace=ns AND run_id=run;
             ELSE
               IF OLD.receipt IS NOT NULL OR NEW.receipt IS NULL THEN RETURN NULL; END IF;
               ns=NEW.namespace;run=NEW.run_id;
               SELECT m.size_bytes INTO size FROM artifact_payload_metadata m
                 JOIN coverage_model_summary s ON s.deployment_namespace=m.deployment_namespace
                   AND s.namespace=ns AND s.run_id=run AND s.session_id=m.session_id
                 WHERE m.deployment_namespace=dep AND m.lifecycle_status='finalized'
                   AND m.artifact_id=substring(NEW.receipt->>'checkpoint_ref' FROM 12)::uuid
                   AND m.sha256=NEW.receipt->>'checkpoint_digest';
               IF size IS NULL THEN
                 UPDATE coverage_model_summary SET volume_ready=FALSE
                   WHERE deployment_namespace=dep AND namespace=ns AND run_id=run;
               ELSE
                 UPDATE coverage_model_summary SET original_bytes=original_bytes+size,
                   original_count=original_count+1
                   WHERE deployment_namespace=dep AND namespace=ns AND run_id=run;
               END IF;
             END IF;
             RETURN NULL;
           END $$""",
        """CREATE TRIGGER coverage_model_volume_source AFTER INSERT ON session_events
           FOR EACH ROW EXECUTE FUNCTION advance_coverage_model_volume()""",
        """CREATE TRIGGER coverage_model_volume_calls AFTER UPDATE ON coverage_model_calls
           FOR EACH ROW EXECUTE FUNCTION advance_coverage_model_volume()""",
        """CREATE FUNCTION invalidate_coverage_model_volume() RETURNS trigger
           LANGUAGE plpgsql AS $$ DECLARE ref TEXT;
           BEGIN
             IF TG_OP='TRUNCATE' THEN
               UPDATE coverage_model_summary SET volume_ready=FALSE;
               RETURN NULL;
             END IF;
             IF TG_OP='UPDATE' AND to_jsonb(OLD)=to_jsonb(NEW) THEN RETURN NULL; END IF;
             ref='artifact://' || OLD.artifact_id::text;
             UPDATE coverage_model_summary s SET volume_ready=FALSE
               FROM coverage_model_calls c
               WHERE c.deployment_namespace=OLD.deployment_namespace AND c.receipt IS NOT NULL
                 AND c.receipt->>'checkpoint_ref'=ref
                 AND (s.deployment_namespace,s.namespace,s.run_id)=
                     (c.deployment_namespace,c.namespace,c.run_id);
             RETURN NULL;
           END $$""",
        """CREATE TRIGGER coverage_model_volume_metadata AFTER UPDATE OR DELETE
           ON artifact_payload_metadata FOR EACH ROW
           EXECUTE FUNCTION invalidate_coverage_model_volume()""",
        """CREATE TRIGGER coverage_model_volume_truncate AFTER TRUNCATE
           ON artifact_payload_metadata FOR EACH STATEMENT
           EXECUTE FUNCTION invalidate_coverage_model_volume()""",
    ),
)
