"""v101: coalesced canonical notification delivery, without Event outbox rows."""

from agent_storage.postgres.migration_types import Migration

STREAM_HINT_RELAY_MIGRATION = Migration(
    version=101,
    name="stream_hint_relay",
    statements=(
        "LOCK TABLE session_streams IN ACCESS EXCLUSIVE MODE",
        """ALTER TABLE session_streams
          ADD COLUMN published_through BIGINT NOT NULL DEFAULT -1,
          ADD COLUMN claim_owner TEXT,
          ADD COLUMN claim_fence BIGINT NOT NULL DEFAULT 0,
          ADD COLUMN lease_expires_at TIMESTAMPTZ,
          ADD COLUMN claimed_through BIGINT,
          ADD COLUMN next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT 'epoch'""",
        # ponytail: historical rows are excluded at cutover, not certified as delivered.
        "UPDATE session_streams SET published_through=current_version",
        """ALTER TABLE session_streams ADD CONSTRAINT stream_hint_relay_shape CHECK (
          published_through >= -1 AND published_through <= current_version AND claim_fence >= 0
          AND ((claim_owner IS NULL AND lease_expires_at IS NULL AND claimed_through IS NULL)
            OR (claim_owner IS NOT NULL AND length(claim_owner) BETWEEN 1 AND 128
              AND lease_expires_at IS NOT NULL AND claimed_through IS NOT NULL
              AND claimed_through >= 0 AND claimed_through <= current_version)))""",
        """CREATE INDEX stream_hint_due ON session_streams
          (deployment_namespace,next_attempt_at,session_id)
          WHERE claim_owner IS NULL AND current_version>published_through""",
        """CREATE INDEX stream_hint_expired ON session_streams
          (deployment_namespace,lease_expires_at,session_id)
          WHERE claim_owner IS NOT NULL AND current_version>published_through""",
    ),
)
