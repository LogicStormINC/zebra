"""PostgreSQL v17 schema for Host registry, replay and audit evidence."""

from agent_storage.postgres.migration_types import Migration

HOST_AUTH_MIGRATION = Migration(
    version=17,
    name="host_authority_registry_replay_audit",
    statements=(
        """
        CREATE TABLE host_authority_registries (
            deployment_namespace TEXT NOT NULL,
            host_app_id TEXT NOT NULL CHECK (
                length(btrim(host_app_id)) BETWEEN 1 AND 128
            ),
            namespace_id TEXT NOT NULL CHECK (
                length(btrim(namespace_id)) BETWEEN 1 AND 512
            ),
            issuer TEXT NOT NULL CHECK (
                length(btrim(issuer)) BETWEEN 1 AND 2048
            ),
            audience TEXT NOT NULL CHECK (
                length(btrim(audience)) BETWEEN 1 AND 512
            ),
            jwks_uri TEXT NOT NULL CHECK (
                length(btrim(jwks_uri)) BETWEEN 1 AND 2048
            ),
            allowed_origins JSONB NOT NULL CHECK (
                jsonb_typeof(allowed_origins) = 'array'
            ),
            algorithms JSONB NOT NULL CHECK (
                jsonb_typeof(algorithms) = 'array'
            ),
            policy_version TEXT NOT NULL CHECK (
                length(btrim(policy_version)) BETWEEN 1 AND 128
            ),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, host_app_id, namespace_id),
            UNIQUE (deployment_namespace, host_app_id, namespace_id, issuer),
            CHECK (created_at <= updated_at)
        )
        """,
        """
        CREATE INDEX host_authority_registries_issuer
        ON host_authority_registries (
            deployment_namespace, issuer, host_app_id, namespace_id
        ) WHERE active
        """,
        """
        CREATE TABLE host_grant_replay_ledger (
            deployment_namespace TEXT NOT NULL,
            issuer TEXT NOT NULL CHECK (length(btrim(issuer)) BETWEEN 1 AND 2048),
            jti TEXT NOT NULL CHECK (length(btrim(jti)) BETWEEN 1 AND 512),
            host_app_id TEXT NOT NULL CHECK (
                length(btrim(host_app_id)) BETWEEN 1 AND 128
            ),
            namespace_id TEXT NOT NULL CHECK (
                length(btrim(namespace_id)) BETWEEN 1 AND 512
            ),
            algorithm TEXT NOT NULL CHECK (algorithm IN ('RS256', 'ES256')),
            grant_digest TEXT NOT NULL CHECK (
                grant_digest ~ '^[0-9a-f]{64}$'
            ),
            scopes_digest TEXT NOT NULL CHECK (
                scopes_digest ~ '^[0-9a-f]{64}$'
            ),
            resource_digest TEXT NOT NULL CHECK (
                resource_digest ~ '^[0-9a-f]{64}$'
            ),
            expires_at TIMESTAMPTZ NOT NULL,
            seen_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, issuer, jti)
        )
        """,
        """
        CREATE INDEX host_grant_replay_expiry
        ON host_grant_replay_ledger (deployment_namespace, expires_at)
        """,
        """
        CREATE TABLE host_grant_audit (
            deployment_namespace TEXT NOT NULL,
            audit_id BIGINT GENERATED ALWAYS AS IDENTITY,
            issuer TEXT NOT NULL CHECK (length(btrim(issuer)) BETWEEN 1 AND 2048),
            jti TEXT NOT NULL CHECK (length(btrim(jti)) BETWEEN 1 AND 512),
            host_app_id TEXT NOT NULL CHECK (
                length(btrim(host_app_id)) BETWEEN 1 AND 128
            ),
            namespace_id TEXT NOT NULL CHECK (
                length(btrim(namespace_id)) BETWEEN 1 AND 512
            ),
            algorithm TEXT NOT NULL CHECK (algorithm IN ('RS256', 'ES256')),
            outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'replay', 'rejected')),
            reason TEXT NOT NULL CHECK (
                length(btrim(reason)) BETWEEN 1 AND 512
            ),
            grant_digest TEXT NOT NULL CHECK (
                grant_digest ~ '^[0-9a-f]{64}$'
            ),
            scopes_digest TEXT NOT NULL CHECK (
                scopes_digest ~ '^[0-9a-f]{64}$'
            ),
            resource_digest TEXT NOT NULL CHECK (
                resource_digest ~ '^[0-9a-f]{64}$'
            ),
            observed_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, audit_id)
        )
        """,
        """
        CREATE INDEX host_grant_audit_lookup
        ON host_grant_audit (
            deployment_namespace, issuer, jti, observed_at, audit_id
        )
        """,
    ),
)
