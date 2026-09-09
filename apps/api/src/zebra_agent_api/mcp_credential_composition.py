"""Compose encrypted storage with an operator-mounted master key, never user keys."""

from agent_security.mcp_credential_management import McpCredentialManagement
from agent_security.mcp_credential_protection import mounted_mcp_protector
from agent_storage import CloudCompositionSettings
from agent_storage.postgres.mcp_credentials import PostgresMcpCredentialStore
from zebra_agent_config import ZebraAgentSettings


def compose_mcp_credentials(
    settings: ZebraAgentSettings,
    cloud: CloudCompositionSettings,
) -> McpCredentialManagement:
    config = settings.mcp_credentials
    protector = mounted_mcp_protector(config.secret_root, config.key_handle, config.key_version)
    return McpCredentialManagement(
        PostgresMcpCredentialStore(cloud.dsn, deployment_namespace=cloud.deployment_namespace),
        protector,
        cloud.deployment_namespace,
    )
