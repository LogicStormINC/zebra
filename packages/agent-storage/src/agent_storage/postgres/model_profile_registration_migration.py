"""Shared durable model revisions and original registration operations."""

from agent_storage.postgres.migration_types import Migration

MODEL_PROFILE_REGISTRATION_MIGRATION = Migration(
    version=124,
    name="model_profile_registration",
    statements=(
        """CREATE TABLE model_profile_revisions (
            scope_digest TEXT NOT NULL,
            model_config_id TEXT NOT NULL,
            revision BIGINT NOT NULL CHECK (revision > 0),
            profile_id TEXT NOT NULL,
            profile JSONB NOT NULL,
            request_digest TEXT NOT NULL,
            PRIMARY KEY (scope_digest, model_config_id, revision),
            UNIQUE (scope_digest, profile_id, revision)
        )""",
        """CREATE TABLE model_profile_registration_operations (
            scope_digest TEXT NOT NULL,
            operation_id UUID NOT NULL,
            model_config_id TEXT NOT NULL,
            revision BIGINT NOT NULL,
            PRIMARY KEY (scope_digest, operation_id),
            FOREIGN KEY (scope_digest, model_config_id, revision)
                REFERENCES model_profile_revisions(scope_digest, model_config_id, revision)
        )""",
    ),
)
