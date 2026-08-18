"""PostgreSQL v8 schema for the Handoff aggregate and fenced dispatch."""

from agent_storage.postgres.migration_types import Migration

HANDOFF_MIGRATION = Migration(
    version=8,
    name="fenced_session_handoff",
    statements=(
        """
        CREATE TABLE handoff_operations (
            deployment_namespace TEXT NOT NULL,
            operation_id UUID NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('preparing', 'committed', 'aborted')),
            source_session_id UUID NOT NULL,
            target_session_id UUID NOT NULL,
            handoff_id UUID NOT NULL,
            idempotency_key_hash TEXT NOT NULL
                CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
            request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            expected_source_stream_version BIGINT NOT NULL
                CHECK (expected_source_stream_version >= 0),
            source_lease_epoch UUID,
            source_lease_fencing_token BIGINT CHECK (source_lease_fencing_token >= 1),
            source_lease_owner_instance_id TEXT,
            authority_revision TEXT NOT NULL CHECK (length(btrim(authority_revision)) > 0),
            workspace_revision JSONB NOT NULL CHECK (jsonb_typeof(workspace_revision) = 'object'),
            task_profile_revision TEXT NOT NULL
                CHECK (length(btrim(task_profile_revision)) > 0),
            effective_depth_limit INTEGER NOT NULL
                CHECK (effective_depth_limit BETWEEN 1 AND 128),
            artifact_id TEXT CHECK (
                artifact_id IS NULL OR length(btrim(artifact_id)) > 0
            ),
            abort_code TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, operation_id),
            UNIQUE (deployment_namespace, source_session_id, idempotency_key_hash),
            UNIQUE (deployment_namespace, target_session_id),
            UNIQUE (deployment_namespace, handoff_id),
            UNIQUE (
                deployment_namespace, handoff_id, source_session_id,
                target_session_id, artifact_id
            ),
            FOREIGN KEY (deployment_namespace, source_session_id)
                REFERENCES session_streams (deployment_namespace, session_id),
            CHECK ((source_lease_epoch IS NULL) =
                (source_lease_fencing_token IS NULL)),
            CHECK ((source_lease_epoch IS NULL) =
                (source_lease_owner_instance_id IS NULL)),
            CHECK (source_lease_owner_instance_id IS NULL OR
                length(btrim(source_lease_owner_instance_id)) > 0),
            CHECK (created_at <= updated_at),
            CHECK (
                (status = 'preparing' AND artifact_id IS NULL AND abort_code IS NULL)
                OR (status = 'committed' AND artifact_id IS NOT NULL AND abort_code IS NULL)
                OR (status = 'aborted' AND artifact_id IS NULL
                    AND length(btrim(abort_code)) > 0)
            )
        )
        """,
        """
        CREATE TABLE session_handoff_envelopes (
            deployment_namespace TEXT NOT NULL,
            handoff_id UUID NOT NULL,
            source_session_id UUID NOT NULL,
            target_session_id UUID NOT NULL,
            artifact_id TEXT NOT NULL CHECK (length(btrim(artifact_id)) > 0),
            envelope JSONB NOT NULL CHECK (jsonb_typeof(envelope) = 'object'),
            checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL,
            CHECK (envelope ->> 'handoff_id' = handoff_id::text),
            CHECK (envelope ->> 'source_session_id' = source_session_id::text),
            CHECK (envelope ->> 'target_session_id' = target_session_id::text),
            CHECK (envelope ->> 'checksum' = checksum),
            PRIMARY KEY (deployment_namespace, handoff_id),
            UNIQUE (deployment_namespace, artifact_id),
            UNIQUE (deployment_namespace, handoff_id, target_session_id),
            FOREIGN KEY (
                deployment_namespace, handoff_id, source_session_id,
                target_session_id, artifact_id
            ) REFERENCES handoff_operations (
                deployment_namespace, handoff_id, source_session_id,
                target_session_id, artifact_id
            ) DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (deployment_namespace, source_session_id)
                REFERENCES session_streams (deployment_namespace, session_id)
                DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (deployment_namespace, target_session_id)
                REFERENCES session_streams (deployment_namespace, session_id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """,
        """
        CREATE FUNCTION reject_session_handoff_envelope_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('zebra.allow_handoff_envelope_delete', true) = 'on'
            THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'session Handoff Envelopes are immutable'
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE TRIGGER session_handoff_envelopes_immutable
        BEFORE UPDATE OR DELETE ON session_handoff_envelopes
        FOR EACH ROW EXECUTE FUNCTION reject_session_handoff_envelope_mutation()
        """,
        """
        CREATE TABLE handoff_dispatch_outbox (
            deployment_namespace TEXT NOT NULL,
            delivery_id UUID NOT NULL,
            child_session_id UUID NOT NULL,
            handoff_id UUID NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'acked')),
            claim_token TEXT,
            claim_epoch UUID,
            claim_fencing_token BIGINT CHECK (claim_fencing_token >= 1),
            claim_owner_instance_id TEXT,
            claim_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            acked_at TIMESTAMPTZ,
            PRIMARY KEY (deployment_namespace, delivery_id),
            UNIQUE (deployment_namespace, child_session_id),
            FOREIGN KEY (deployment_namespace, handoff_id, child_session_id)
                REFERENCES session_handoff_envelopes (
                    deployment_namespace, handoff_id, target_session_id
                ) DEFERRABLE INITIALLY DEFERRED,
            CHECK (claim_owner_instance_id IS NULL OR
                length(btrim(claim_owner_instance_id)) > 0),
            CHECK (
                (status = 'claimed') = (
                    claim_token IS NOT NULL
                    AND claim_epoch IS NOT NULL
                    AND claim_fencing_token IS NOT NULL
                    AND claim_owner_instance_id IS NOT NULL
                    AND claim_expires_at IS NOT NULL
                )
            ),
            CHECK (status = 'claimed' OR (
                claim_token IS NULL AND claim_epoch IS NULL
                AND claim_fencing_token IS NULL
                AND claim_owner_instance_id IS NULL AND claim_expires_at IS NULL
            )),
            CHECK ((status = 'acked') = (acked_at IS NOT NULL)),
            CHECK (acked_at IS NULL OR acked_at >= created_at)
        )
        """,
        """
        CREATE INDEX handoff_dispatch_pending
        ON handoff_dispatch_outbox (deployment_namespace, created_at, delivery_id)
        WHERE status = 'pending'
        """,
        """
        CREATE INDEX handoff_dispatch_reclaim
        ON handoff_dispatch_outbox (
            deployment_namespace, claim_expires_at, delivery_id
        ) WHERE status = 'claimed'
        """,
    ),
)
