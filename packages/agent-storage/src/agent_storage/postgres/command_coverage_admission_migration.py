"""Strict command requirements and final commit-clock validation (no activation)."""

from agent_storage.postgres.migration_types import Migration

COMMAND_COVERAGE_ADMISSION_MIGRATION = Migration(
    version=83,
    name="strict_command_capability_requirements",
    statements=(
        """ALTER TABLE worker_process_capabilities ADD COLUMN attestation_digest TEXT
           CHECK (attestation_digest ~ '^[0-9a-f]{64}$')""",
        """CREATE TABLE command_coverage_requirements (
            deployment_namespace TEXT NOT NULL,
            accepted_event_id UUID NOT NULL,
            task_id UUID NOT NULL,
            session_id UUID NOT NULL,
            bootstrap_event_id UUID NOT NULL,
            binding_revision BIGINT NOT NULL,
            binding_digest TEXT NOT NULL CHECK (binding_digest ~ '^[0-9a-f]{64}$'),
            admission_digest TEXT NOT NULL CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
            contract TEXT NOT NULL CHECK (length(contract) BETWEEN 1 AND 128),
            configuration_digest TEXT NOT NULL CHECK (configuration_digest ~ '^[0-9a-f]{64}$'),
            PRIMARY KEY (deployment_namespace,accepted_event_id),
            FOREIGN KEY (deployment_namespace,accepted_event_id)
                REFERENCES session_events (deployment_namespace,event_id),
            FOREIGN KEY (deployment_namespace,bootstrap_event_id)
                REFERENCES session_events (deployment_namespace,event_id),
            FOREIGN KEY (deployment_namespace,task_id,binding_revision)
                REFERENCES task_binding_snapshots (deployment_namespace,task_id,binding_revision)
        )""",
        """CREATE INDEX command_coverage_task_configuration ON command_coverage_requirements
           (deployment_namespace,task_id,session_id)""",
        """CREATE FUNCTION check_command_coverage_commit() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE final_now TIMESTAMPTZ; host_expiry TIMESTAMPTZ; context_expiry TIMESTAMPTZ;
                runtime_deadline TIMESTAMPTZ;
        BEGIN
          final_now := clock_timestamp();
          IF NOT EXISTS (
            SELECT 1 FROM command_wakeup_rollouts r
            WHERE r.deployment_namespace=NEW.deployment_namespace AND r.admission_enabled
          ) OR NOT EXISTS (
            SELECT 1 FROM worker_process_capabilities c JOIN control_plane_epochs e
              USING (deployment_namespace,epoch)
            WHERE c.deployment_namespace=NEW.deployment_namespace
              AND c.contract=NEW.contract AND c.configuration_digest=NEW.configuration_digest
              AND c.revoked_at IS NULL AND c.expires_at>final_now
              AND c.attestation_digest IS NOT NULL AND c.database_name=current_database()
              AND c.schema_name=current_schema()
              AND c.schema_oid=current_schema()::regnamespace::oid
          ) OR NOT EXISTS (
            SELECT 1 FROM session_command_pending p JOIN broker_outbox o
              ON o.deployment_namespace=p.deployment_namespace AND o.scope_key=p.scope_key
              AND o.operation_id=p.command_id AND o.wake_generation=p.current_generation
              AND o.message_type='zebra.session.command.ready'
            WHERE p.deployment_namespace=NEW.deployment_namespace
              AND p.accepted_event_id=NEW.accepted_event_id AND p.session_id=NEW.session_id
          ) THEN RAISE EXCEPTION 'strict command native capability or wake unavailable'; END IF;
          SELECT (b.snapshot_json->'host_capability'->>'grant_expires_at')::timestamptz,
                 (b.snapshot_json->'host_capability'->'host_context'->>'expires_at')::timestamptz
            INTO host_expiry,context_expiry FROM task_binding_snapshots b
            WHERE b.deployment_namespace=NEW.deployment_namespace AND b.task_id=NEW.task_id
              AND b.binding_revision=NEW.binding_revision AND b.binding_digest=NEW.binding_digest;
          IF host_expiry IS NULL OR host_expiry<=final_now OR context_expiry IS NULL
            OR context_expiry<=final_now THEN
            RAISE EXCEPTION 'strict command Host authority expired before commit';
          END IF;
          SELECT e.created_at + make_interval(secs =>
                 (e.payload->'coverage_admission'->>'max_runtime_seconds')::integer)
            INTO runtime_deadline FROM session_events e
            WHERE e.deployment_namespace=NEW.deployment_namespace
              AND e.event_id=NEW.bootstrap_event_id AND e.session_id=NEW.session_id
              AND e.event_type='task_prepared' AND e.sequence=2;
          IF runtime_deadline IS NULL OR runtime_deadline<=final_now THEN
            RAISE EXCEPTION 'strict Task runtime deadline expired before commit';
          END IF;
          IF EXISTS (
            SELECT 1 FROM task_binding_snapshots b
            WHERE b.deployment_namespace=NEW.deployment_namespace AND b.task_id=NEW.task_id
              AND b.binding_revision>NEW.binding_revision
          ) OR NOT EXISTS (
            SELECT 1 FROM task_binding_snapshots b JOIN host_authority_registries h
              ON h.deployment_namespace=b.deployment_namespace
              AND h.host_app_id=b.snapshot_json->'host_capability'->>'host_app_id'
              AND h.namespace_id=b.snapshot_json->'host_capability'->>'namespace_id'
              AND h.issuer=b.snapshot_json->'host_capability'->>'authority_issuer'
            WHERE b.deployment_namespace=NEW.deployment_namespace AND b.task_id=NEW.task_id
              AND b.binding_revision=NEW.binding_revision AND h.active
          ) THEN RAISE EXCEPTION 'strict command current Host binding changed'; END IF;
          RETURN NEW;
        END $$""",
        """CREATE CONSTRAINT TRIGGER command_coverage_commit
           AFTER INSERT OR UPDATE ON command_coverage_requirements
           DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
           EXECUTE FUNCTION check_command_coverage_commit()""",
    ),
)
