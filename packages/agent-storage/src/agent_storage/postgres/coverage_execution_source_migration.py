"""v85: retain native accepted sources referenced by execution receipts."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_EXECUTION_SOURCE_MIGRATION = Migration(
    version=85,
    name="coverage_execution_source_seal",
    statements=(
        """UPDATE session_events e SET created_at=e.created_at
           FROM coverage_execution_receipts r WHERE
             r.deployment_namespace=e.deployment_namespace AND r.event_id=e.event_id""",
        """CREATE FUNCTION retain_coverage_execution_source() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF TG_OP='TRUNCATE' THEN
               IF EXISTS (SELECT 1 FROM coverage_execution_receipts LIMIT 1) THEN
                 RAISE EXCEPTION 'coverage execution sources are sealed';
               END IF;
               RETURN NULL;
             END IF;
             IF EXISTS (SELECT 1 FROM coverage_execution_receipts
               WHERE deployment_namespace=OLD.deployment_namespace AND event_id=OLD.event_id) THEN
               RAISE EXCEPTION 'coverage execution sources are sealed';
             END IF;
             IF TG_OP='DELETE' THEN RETURN OLD; END IF;
             RETURN NEW;
           END $$""",
        """CREATE TRIGGER coverage_execution_source_retention
           BEFORE UPDATE OR DELETE ON session_events FOR EACH ROW
           EXECUTE FUNCTION retain_coverage_execution_source()""",
        """CREATE TRIGGER coverage_execution_source_no_truncate
           BEFORE TRUNCATE ON session_events FOR EACH STATEMENT
           EXECUTE FUNCTION retain_coverage_execution_source()""",
        """CREATE FUNCTION seal_coverage_execution_source() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF EXISTS (SELECT 1 FROM coverage_execution_receipts
               WHERE deployment_namespace=NEW.deployment_namespace AND event_id=NEW.event_id) THEN
               RETURN NEW;
             END IF;
             -- A real row-version write serializes even stale RR writers. Keep
             -- the Event JSON unchanged: independent model witnesses bind it.
             UPDATE session_events SET created_at=created_at
               WHERE deployment_namespace=NEW.deployment_namespace AND event_id=NEW.event_id
                 AND session_id=NEW.session_id AND sequence=NEW.sequence
                 AND payload->>'namespace'=NEW.namespace AND payload->>'run_id'=NEW.run_id
                 AND event_type='coverage_batch_accepted';
             IF NOT FOUND THEN
               RAISE EXCEPTION 'coverage execution receipt requires native accepted source';
             END IF;
             RETURN NEW;
           END $$""",
        """CREATE TRIGGER coverage_execution_receipt_source_seal
           BEFORE INSERT ON coverage_execution_receipts FOR EACH ROW
           EXECUTE FUNCTION seal_coverage_execution_source()""",
    ),
)
