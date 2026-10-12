"""v99: sealed execution sources still permit guarded derived Task allocation."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_EXECUTION_POSITIONS_MIGRATION = Migration(
    version=99,
    name="coverage_execution_source_positions",
    statements=(
        # Manifest membership must track source changes, not the late projection
        # coordinates. Existing invalidated seals are never reset by this upgrade.
        "DROP TRIGGER coverage_membership_source_session_events ON session_events",
        """CREATE TRIGGER coverage_membership_source_session_events
           AFTER INSERT OR DELETE ON session_events FOR EACH ROW
           EXECUTE FUNCTION advance_coverage_membership()""",
        """CREATE TRIGGER coverage_membership_source_update AFTER UPDATE ON session_events
           FOR EACH ROW WHEN (coverage_model_event_source(to_jsonb(OLD)) IS DISTINCT FROM
                              coverage_model_event_source(to_jsonb(NEW)))
           EXECUTE FUNCTION advance_coverage_membership()""",
        # Reuse v96's exact three-field exclusion. Task/source guards still
        # validate allocation; no-op writes and all business mutations stay sealed.
        """CREATE OR REPLACE FUNCTION retain_coverage_execution_source() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF TG_OP='TRUNCATE' THEN
               IF EXISTS (SELECT 1 FROM coverage_execution_receipts LIMIT 1) THEN
                 RAISE EXCEPTION 'coverage execution sources are sealed';
               END IF;
               RETURN NULL;
             END IF;
             IF TG_OP='UPDATE' THEN
               IF to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW)
                  AND coverage_model_event_source(to_jsonb(OLD)) IS NOT DISTINCT FROM
                      coverage_model_event_source(to_jsonb(NEW)) THEN
                 RETURN NEW;
               END IF;
             END IF;
             IF EXISTS (SELECT 1 FROM coverage_execution_receipts
               WHERE deployment_namespace=OLD.deployment_namespace AND event_id=OLD.event_id) THEN
               RAISE EXCEPTION 'coverage execution sources are sealed';
             END IF;
             IF TG_OP='DELETE' THEN RETURN OLD; END IF;
             RETURN NEW;
           END $$""",
    ),
)
