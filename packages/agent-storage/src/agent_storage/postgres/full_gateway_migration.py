"""PostgreSQL v60: permit gateway-mediated Web and MCP in one cloud task."""

from agent_storage.postgres.migration_types import Migration

FULL_GATEWAY_MIGRATION = Migration(
    version=60,
    name="full_gateway_network_profile",
    statements=(
        """
        ALTER TABLE workspace_projections
            DROP CONSTRAINT workspace_projections_network_profile_check
        """,
        """
        ALTER TABLE workspace_projections
            ADD CONSTRAINT workspace_projections_network_profile_check
            CHECK (network_profile IN (
                'none', 'setup-only', 'domain-allowlist', 'mcp-proxy-only',
                'git-proxy-only', 'full-trusted-local', 'full-gateway'
            ))
        """,
    ),
)
