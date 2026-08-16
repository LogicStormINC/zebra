"""PostgreSQL v19 schema for the Agent Definition Registry authority."""

from agent_storage.postgres.migration_types import Migration

AGENT_REGISTRY_MIGRATION = Migration(
    version=19,
    name="agent_definition_registry",
    statements=(
        """
        CREATE TABLE agent_definition_records (
            authority_issuer TEXT NOT NULL CHECK (
                length(btrim(authority_issuer)) BETWEEN 1 AND 2048
            ),
            namespace_id TEXT NOT NULL CHECK (
                length(btrim(namespace_id)) BETWEEN 1 AND 255
            ),
            definition_id UUID NOT NULL,
            name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 256),
            description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 4096),
            revision BIGINT NOT NULL CHECK (revision >= 0),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (authority_issuer, namespace_id, definition_id)
        )
        """,
        """
        CREATE TABLE agent_definition_versions (
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            definition_id UUID NOT NULL,
            version_id UUID NOT NULL,
            version BIGINT NOT NULL CHECK (version >= 1),
            schema_version TEXT NOT NULL
                CHECK (length(btrim(schema_version)) BETWEEN 1 AND 64),
            model_policy_ref TEXT NOT NULL
                CHECK (length(btrim(model_policy_ref)) BETWEEN 1 AND 512),
            tool_profile_ref TEXT NOT NULL
                CHECK (length(btrim(tool_profile_ref)) BETWEEN 1 AND 512),
            skill_snapshot_digest TEXT NOT NULL CHECK (length(skill_snapshot_digest) = 64),
            memory_policy_ref TEXT NOT NULL
                CHECK (length(btrim(memory_policy_ref)) BETWEEN 1 AND 512),
            security_policy_ref TEXT NOT NULL
                CHECK (length(btrim(security_policy_ref)) BETWEEN 1 AND 512),
            evaluation_profile_ref TEXT NOT NULL
                CHECK (length(btrim(evaluation_profile_ref)) BETWEEN 1 AND 512),
            runtime_profile_ref TEXT NOT NULL
                CHECK (length(btrim(runtime_profile_ref)) BETWEEN 1 AND 512),
            definition_digest TEXT NOT NULL CHECK (length(definition_digest) = 64),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (authority_issuer, namespace_id, definition_id, version_id),
            UNIQUE (authority_issuer, namespace_id, definition_id, version),
            FOREIGN KEY (authority_issuer, namespace_id, definition_id)
                REFERENCES agent_definition_records (
                    authority_issuer, namespace_id, definition_id
                )
        )
        """,
        """
        CREATE TABLE agent_release_records (
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            definition_id UUID NOT NULL,
            environment TEXT NOT NULL
                CHECK (length(btrim(environment)) BETWEEN 1 AND 128),
            release_id UUID NOT NULL,
            version_id UUID NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('published', 'deprecated', 'revoked')),
            revision BIGINT NOT NULL CHECK (revision >= 1),
            definition_digest TEXT NOT NULL CHECK (length(definition_digest) = 64),
            actor_ref TEXT NOT NULL
                CHECK (length(btrim(actor_ref)) BETWEEN 1 AND 512),
            reason_class TEXT CHECK (
                reason_class IS NULL OR length(btrim(reason_class)) BETWEEN 1 AND 128
            ),
            effective_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (authority_issuer, namespace_id, definition_id, environment, release_id),
            UNIQUE (authority_issuer, namespace_id, definition_id, environment, revision),
            FOREIGN KEY (authority_issuer, namespace_id, definition_id, version_id)
                REFERENCES agent_definition_versions (
                    authority_issuer, namespace_id, definition_id, version_id
                ),
            CHECK (status = 'published' OR reason_class IS NOT NULL)
        )
        """,
        """
        CREATE UNIQUE INDEX agent_release_single_published
        ON agent_release_records (
            authority_issuer, namespace_id, definition_id, environment
        ) WHERE status = 'published'
        """,
        """
        CREATE TABLE agent_definition_eval_evidence (
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            definition_id UUID NOT NULL,
            version_id UUID NOT NULL,
            evidence_id UUID NOT NULL,
            definition_digest TEXT NOT NULL CHECK (length(definition_digest) = 64),
            binding_purpose TEXT NOT NULL CHECK (binding_purpose = 'eval'),
            passed BOOLEAN NOT NULL,
            evaluator_actor TEXT NOT NULL
                CHECK (length(btrim(evaluator_actor)) BETWEEN 1 AND 512),
            case_summary JSONB NOT NULL
                CHECK (jsonb_typeof(case_summary) = 'object'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (authority_issuer, namespace_id, definition_id, version_id, evidence_id),
            FOREIGN KEY (authority_issuer, namespace_id, definition_id, version_id)
                REFERENCES agent_definition_versions (
                    authority_issuer, namespace_id, definition_id, version_id
                )
        )
        """,
        """
        CREATE TABLE agent_definition_drafts (
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            definition_id UUID NOT NULL,
            name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 256),
            description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 4096),
            model_policy_ref TEXT NOT NULL
                CHECK (length(btrim(model_policy_ref)) BETWEEN 1 AND 512),
            tool_profile_ref TEXT NOT NULL
                CHECK (length(btrim(tool_profile_ref)) BETWEEN 1 AND 512),
            skill_snapshot_digest TEXT NOT NULL CHECK (length(skill_snapshot_digest) = 64),
            memory_policy_ref TEXT NOT NULL
                CHECK (length(btrim(memory_policy_ref)) BETWEEN 1 AND 512),
            security_policy_ref TEXT NOT NULL
                CHECK (length(btrim(security_policy_ref)) BETWEEN 1 AND 512),
            evaluation_profile_ref TEXT NOT NULL
                CHECK (length(btrim(evaluation_profile_ref)) BETWEEN 1 AND 512),
            runtime_profile_ref TEXT NOT NULL
                CHECK (length(btrim(runtime_profile_ref)) BETWEEN 1 AND 512),
            revision BIGINT NOT NULL CHECK (revision >= 0),
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (authority_issuer, namespace_id, definition_id),
            FOREIGN KEY (authority_issuer, namespace_id, definition_id)
                REFERENCES agent_definition_records (
                    authority_issuer, namespace_id, definition_id
                )
        )
        """,
        """
        CREATE TABLE agent_definition_draft_validations (
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            definition_id UUID NOT NULL,
            validation_id UUID NOT NULL,
            draft_revision BIGINT NOT NULL CHECK (draft_revision >= 0),
            status TEXT NOT NULL CHECK (status IN ('passed', 'failed')),
            issues JSONB NOT NULL CHECK (jsonb_typeof(issues) = 'array'),
            evaluated_at TIMESTAMPTZ NOT NULL,
            evaluator_actor TEXT NOT NULL
                CHECK (length(btrim(evaluator_actor)) BETWEEN 1 AND 2048),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (authority_issuer, namespace_id, definition_id, validation_id),
            FOREIGN KEY (authority_issuer, namespace_id, definition_id)
                REFERENCES agent_definition_records (
                    authority_issuer, namespace_id, definition_id
                )
        )
        """,
        """
        CREATE INDEX agent_definition_draft_validations_latest
        ON agent_definition_draft_validations (
            authority_issuer, namespace_id, definition_id, created_at DESC
        )
        """,
    ),
)
