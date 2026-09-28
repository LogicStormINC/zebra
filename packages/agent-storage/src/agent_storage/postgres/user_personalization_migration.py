"""PostgreSQL v59: principal-scoped Agent personalization instructions."""

from agent_storage.postgres.migration_types import Migration

USER_PERSONALIZATION_MIGRATION = Migration(
    version=59,
    name="user_personalization_instructions",
    statements=(
        """
        CREATE TABLE user_personalization_settings (
            deployment_namespace TEXT NOT NULL,
            user_id TEXT NOT NULL CHECK (length(btrim(user_id)) > 0),
            instructions TEXT,
            revision BIGINT NOT NULL CHECK (revision >= 1),
            operator TEXT NOT NULL CHECK (length(btrim(operator)) > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, user_id),
            CHECK (instructions IS NULL OR (
                length(btrim(instructions)) > 0 AND length(instructions) <= 12000
            )),
            CHECK (updated_at >= created_at)
        )
        """,
    ),
)
