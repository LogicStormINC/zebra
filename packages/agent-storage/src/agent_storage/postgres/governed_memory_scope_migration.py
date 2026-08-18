"""PostgreSQL v21: Definition scope columns on governed memory records."""

from agent_storage.postgres.migration_types import Migration

GOVERNED_MEMORY_SCOPE_MIGRATION = Migration(
    version=21,
    name="governed_memory_definition_scope",
    statements=(
        """
        ALTER TABLE governed_memory_records
        ADD COLUMN authority_issuer TEXT CHECK (
            authority_issuer IS NULL
            OR length(btrim(authority_issuer)) BETWEEN 1 AND 2048
        ),
        ADD COLUMN namespace_id TEXT CHECK (
            namespace_id IS NULL OR length(btrim(namespace_id)) BETWEEN 1 AND 255
        ),
        ADD COLUMN definition_id UUID,
        ADD CONSTRAINT governed_memory_scope_all_or_none CHECK (
            (authority_issuer IS NULL AND namespace_id IS NULL AND definition_id IS NULL)
            OR (authority_issuer IS NOT NULL AND namespace_id IS NOT NULL
                AND definition_id IS NOT NULL)
        )
        """,
        """
        DO $$
        DECLARE constraint_name record;
        BEGIN
            FOR constraint_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'governed_memory_records'::regclass
                  AND pg_get_constraintdef(oid) LIKE 'CHECK (((visibility %'
            LOOP
                EXECUTE format(
                    'ALTER TABLE governed_memory_records DROP CONSTRAINT %I',
                    constraint_name.conname
                );
            END LOOP;
        END $$;
        """,
        """
        ALTER TABLE governed_memory_records
        ADD CONSTRAINT governed_memory_visibility_repo_scope CHECK (
            authority_issuer IS NOT NULL
            OR visibility != 'repo'
            OR (repo_id IS NOT NULL AND btrim(repo_id) != '')
        ),
        ADD CONSTRAINT governed_memory_visibility_user_scope CHECK (
            authority_issuer IS NOT NULL
            OR visibility != 'user'
            OR (user_id IS NOT NULL AND btrim(user_id) != '')
        ),
        ADD CONSTRAINT governed_memory_visibility_tenant_scope CHECK (
            authority_issuer IS NOT NULL
            OR visibility != 'tenant'
            OR (tenant_id IS NOT NULL AND btrim(tenant_id) != '')
        )
        """,
    ),
)
