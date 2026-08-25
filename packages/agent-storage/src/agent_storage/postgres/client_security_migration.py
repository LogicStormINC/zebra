"""Migration v34: close legacy sessions and pin effect parent streams."""

from agent_storage.postgres.migration_types import Migration

CLIENT_SECURITY_MIGRATION = Migration(
    version=34,
    name="client_session_credentials_and_effect_parent",
    statements=(
        """
        WITH ranked_bindings AS (
            SELECT binding_id,
                   row_number() OVER (
                       PARTITION BY deployment_namespace, host_app_id,
                                    namespace_id, frontend_app_id
                       ORDER BY binding_revision DESC, bound_at DESC,
                                binding_id DESC
                   ) AS duplicate_rank
            FROM frontend_capability_bindings
        )
        DELETE FROM frontend_capability_bindings AS binding
        USING ranked_bindings AS ranked
        WHERE binding.binding_id = ranked.binding_id
          AND ranked.duplicate_rank > 1
        """,
        """
        CREATE UNIQUE INDEX frontend_capability_binding_host_unique
        ON frontend_capability_bindings (
            deployment_namespace, host_app_id, namespace_id, frontend_app_id
        )
        """,
        """
        ALTER TABLE client_sessions ADD COLUMN credential_hash TEXT
        """,
        """
        UPDATE client_sessions
        SET credential_hash = repeat('0', 64), status = 'closed'
        WHERE credential_hash IS NULL
        """,
        """
        ALTER TABLE client_sessions
        ALTER COLUMN credential_hash SET NOT NULL,
        ADD CONSTRAINT client_sessions_credential_hash_shape
            CHECK (credential_hash ~ '^[0-9a-f]{64}$')
        """,
        """
        DELETE FROM client_control_leases AS lease
        WHERE lease.run_binding_id IS NULL
           OR NOT EXISTS (
                SELECT 1 FROM client_run_bindings AS binding
                WHERE binding.deployment_namespace = lease.deployment_namespace
                  AND binding.binding_id = lease.run_binding_id
                  AND binding.task_id = lease.task_id
                  AND binding.run_id = lease.run_id
                  AND binding.client_session_id = lease.client_session_id
           )
        """,
        """
        ALTER TABLE client_control_leases
        ALTER COLUMN run_binding_id SET NOT NULL,
        ADD CONSTRAINT client_control_lease_run_binding_fk
            FOREIGN KEY (deployment_namespace, run_binding_id)
            REFERENCES client_run_bindings (deployment_namespace, binding_id)
            ON DELETE CASCADE
        """,
        """
        ALTER TABLE client_effects ADD COLUMN parent_session_id UUID
        """,
        """
        UPDATE client_effects
        SET parent_session_id = task_id,
            status = CASE
                WHEN status IN ('pending', 'delivered', 'uncertain')
                    THEN 'cancelled'
                ELSE status
            END
        WHERE parent_session_id IS NULL
        """,
        """
        ALTER TABLE client_effects
        ALTER COLUMN parent_session_id SET NOT NULL
        """,
    ),
)
