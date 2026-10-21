"""Additive v111 publication CAS and exact-operation receipts; history untouched."""

from agent_storage.postgres.migration_types import Migration

PUBLICATION_MIGRATION = Migration(
    version=111,
    name="runtime_publication_receipts",
    statements=(
        """CREATE TABLE runtime_publication_heads (
        deployment_namespace TEXT NOT NULL, authority_issuer TEXT NOT NULL,
        namespace_id TEXT NOT NULL, definition_id UUID NOT NULL,
        revision BIGINT NOT NULL CHECK(revision>0),
        PRIMARY KEY(deployment_namespace,authority_issuer,namespace_id,definition_id))""",
        """CREATE TABLE runtime_publication_receipts (
        deployment_namespace TEXT NOT NULL, actor TEXT NOT NULL, operation_id UUID NOT NULL,
        payload_digest TEXT NOT NULL, result JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(deployment_namespace,actor,operation_id))""",
    ),
)
