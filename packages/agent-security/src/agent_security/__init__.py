"""Security exports load on demand; direct SSRF imports remain lightweight."""

from importlib import import_module
from typing import TYPE_CHECKING

# ponytail: keep explicit type-only re-exports grouped, matching their public modules.
# isort: off
if TYPE_CHECKING:
    from agent_security.artifact_access import (
        classify_artifact_access as classify_artifact_access,
        required_policy_profile_for_artifact_access as required_policy_profile_for_artifact_access,
    )
    from agent_security.artifact_access_audit import (
        build_artifact_access_audit_metadata as build_artifact_access_audit_metadata,
    )
    from agent_security.artifact_access_projection import (
        ArtifactAccessProjection as ArtifactAccessProjection,
        build_artifact_access_projection as build_artifact_access_projection,
        policy_rank as policy_rank,
        serialize_artifact_access_projection as serialize_artifact_access_projection,
    )
    from agent_security.artifact_control_audit import (
        build_artifact_control_audit_metadata as build_artifact_control_audit_metadata,
    )
    from agent_security.artifact_retention import (
        EXTENDED_ARTIFACT_RETENTION as EXTENDED_ARTIFACT_RETENTION,
        SHORT_LIVED_ARTIFACT_RETENTION as SHORT_LIVED_ARTIFACT_RETENTION,
        STANDARD_ARTIFACT_RETENTION as STANDARD_ARTIFACT_RETENTION,
        resolve_artifact_retained_until as resolve_artifact_retained_until,
        resolve_artifact_retention_policy as resolve_artifact_retention_policy,
    )
    from agent_security.broker import (
        CredentialBroker as CredentialBroker,
        CredentialBrokerError as CredentialBrokerError,
        CredentialDeniedError as CredentialDeniedError,
        CredentialMissingError as CredentialMissingError,
        CredentialTransportError as CredentialTransportError,
        CredentialUnavailableError as CredentialUnavailableError,
        InMemoryCredentialBroker as InMemoryCredentialBroker,
    )
    from agent_security.capabilities import CredentialCapability as CredentialCapability
    from agent_security.credentials import (
        REDACTED_SECRET as REDACTED_SECRET,
        ScmCredentialBoundary as ScmCredentialBoundary,
        ScmCredentialCapability as ScmCredentialCapability,
        ScmCredentialSettings as ScmCredentialSettings,
    )
    from agent_security.delivery import (
        CommitPolicy as CommitPolicy,
        DeliveryDecision as DeliveryDecision,
        DeliveryDecisionType as DeliveryDecisionType,
        PullRequestPolicy as PullRequestPolicy,
    )
    from agent_security.environment_broker import (
        EnvironmentCredentialBinding as EnvironmentCredentialBinding,
        EnvironmentCredentialBroker as EnvironmentCredentialBroker,
    )
    from agent_security.mcp_proxy_policy import (
        ToolEgressMetadata as ToolEgressMetadata,
        ToolEgressRoute as ToolEgressRoute,
        classify_tool_egress as classify_tool_egress,
    )
    from agent_security.network_profile import (
        DEFAULT_NETWORK_PROFILE as DEFAULT_NETWORK_PROFILE,
        SUPPORTED_NETWORK_PROFILES as SUPPORTED_NETWORK_PROFILES,
        TRUSTED_LOCAL_NETWORK_PROFILE as TRUSTED_LOCAL_NETWORK_PROFILE,
        NetworkProfile as NetworkProfile,
        NetworkProfileError as NetworkProfileError,
        NetworkProfileName as NetworkProfileName,
        parse_network_profile as parse_network_profile,
        resolve_effective_network_profile as resolve_effective_network_profile,
    )
    from agent_security.policy import (
        ApprovalRequest as ApprovalRequest,
        ApprovalRisk as ApprovalRisk,
        LocalPolicyEngine as LocalPolicyEngine,
        PolicyProfile as PolicyProfile,
        build_approval_request as build_approval_request,
        policy_profile as policy_profile,
    )
    from agent_security.secret_store import (
        InMemorySecretStore as InMemorySecretStore,
        LocalSecretStore as LocalSecretStore,
        SecretMaterial as SecretMaterial,
        SecretMissingError as SecretMissingError,
        SecretStore as SecretStore,
        SecretStoreError as SecretStoreError,
        SecretUnavailableError as SecretUnavailableError,
        get_secret_value as get_secret_value,
    )
    from agent_security.setup_egress import (
        SetupDownload as SetupDownload,
        SetupDownloadEvidence as SetupDownloadEvidence,
        SetupDownloadTransport as SetupDownloadTransport,
        SetupEgressError as SetupEgressError,
        SetupEgressGateway as SetupEgressGateway,
        TemporarySetupCredential as TemporarySetupCredential,
    )
    from agent_security.host_grant import (
        DecodedHostGrant as DecodedHostGrant,
        HostGrantAlgorithmError as HostGrantAlgorithmError,
        HostGrantBindingError as HostGrantBindingError,
        HostGrantSecurityError as HostGrantSecurityError,
        HostGrantVerificationConfig as HostGrantVerificationConfig,
        HostGrantVerifier as HostGrantVerifier,
        JwtAlgorithm as JwtAlgorithm,
        VerifiedHostGrant as VerifiedHostGrant,
    )
    from agent_security.jwt_adapter import (
        CachingJwksKeyResolver as CachingJwksKeyResolver,
        DecodedJwtGrant as DecodedJwtGrant,
        HostGrantDecodeError as HostGrantDecodeError,
        JwksKeyResolver as JwksKeyResolver,
        PyJwtHostGrantDecoder as PyJwtHostGrantDecoder,
    )
# isort: on

# Preserve the historical star-import contract as well as every named alias.
__all__ = [
    "DecodedHostGrant",
    "HostGrantAlgorithmError",
    "HostGrantBindingError",
    "HostGrantSecurityError",
    "HostGrantVerificationConfig",
    "HostGrantVerifier",
    "JwtAlgorithm",
    "VerifiedHostGrant",
    "CachingJwksKeyResolver",
    "DecodedJwtGrant",
    "HostGrantDecodeError",
    "JwksKeyResolver",
    "PyJwtHostGrantDecoder",
]

_EXPORTS = {
    "classify_artifact_access": ("agent_security.artifact_access", "classify_artifact_access"),
    "required_policy_profile_for_artifact_access": (
        "agent_security.artifact_access",
        "required_policy_profile_for_artifact_access",
    ),
    "build_artifact_access_audit_metadata": (
        "agent_security.artifact_access_audit",
        "build_artifact_access_audit_metadata",
    ),
    "ArtifactAccessProjection": (
        "agent_security.artifact_access_projection",
        "ArtifactAccessProjection",
    ),
    "build_artifact_access_projection": (
        "agent_security.artifact_access_projection",
        "build_artifact_access_projection",
    ),
    "policy_rank": ("agent_security.artifact_access_projection", "policy_rank"),
    "serialize_artifact_access_projection": (
        "agent_security.artifact_access_projection",
        "serialize_artifact_access_projection",
    ),
    "build_artifact_control_audit_metadata": (
        "agent_security.artifact_control_audit",
        "build_artifact_control_audit_metadata",
    ),
    "EXTENDED_ARTIFACT_RETENTION": (
        "agent_security.artifact_retention",
        "EXTENDED_ARTIFACT_RETENTION",
    ),
    "SHORT_LIVED_ARTIFACT_RETENTION": (
        "agent_security.artifact_retention",
        "SHORT_LIVED_ARTIFACT_RETENTION",
    ),
    "STANDARD_ARTIFACT_RETENTION": (
        "agent_security.artifact_retention",
        "STANDARD_ARTIFACT_RETENTION",
    ),
    "resolve_artifact_retained_until": (
        "agent_security.artifact_retention",
        "resolve_artifact_retained_until",
    ),
    "resolve_artifact_retention_policy": (
        "agent_security.artifact_retention",
        "resolve_artifact_retention_policy",
    ),
    "CredentialBroker": ("agent_security.broker", "CredentialBroker"),
    "CredentialBrokerError": ("agent_security.broker", "CredentialBrokerError"),
    "CredentialDeniedError": ("agent_security.broker", "CredentialDeniedError"),
    "CredentialMissingError": ("agent_security.broker", "CredentialMissingError"),
    "CredentialTransportError": ("agent_security.broker", "CredentialTransportError"),
    "CredentialUnavailableError": ("agent_security.broker", "CredentialUnavailableError"),
    "InMemoryCredentialBroker": ("agent_security.broker", "InMemoryCredentialBroker"),
    "CredentialCapability": ("agent_security.capabilities", "CredentialCapability"),
    "REDACTED_SECRET": ("agent_security.credentials", "REDACTED_SECRET"),
    "ScmCredentialBoundary": ("agent_security.credentials", "ScmCredentialBoundary"),
    "ScmCredentialCapability": ("agent_security.credentials", "ScmCredentialCapability"),
    "ScmCredentialSettings": ("agent_security.credentials", "ScmCredentialSettings"),
    "CommitPolicy": ("agent_security.delivery", "CommitPolicy"),
    "DeliveryDecision": ("agent_security.delivery", "DeliveryDecision"),
    "DeliveryDecisionType": ("agent_security.delivery", "DeliveryDecisionType"),
    "PullRequestPolicy": ("agent_security.delivery", "PullRequestPolicy"),
    "EnvironmentCredentialBinding": (
        "agent_security.environment_broker",
        "EnvironmentCredentialBinding",
    ),
    "EnvironmentCredentialBroker": (
        "agent_security.environment_broker",
        "EnvironmentCredentialBroker",
    ),
    "ToolEgressMetadata": ("agent_security.mcp_proxy_policy", "ToolEgressMetadata"),
    "ToolEgressRoute": ("agent_security.mcp_proxy_policy", "ToolEgressRoute"),
    "classify_tool_egress": ("agent_security.mcp_proxy_policy", "classify_tool_egress"),
    "DEFAULT_NETWORK_PROFILE": ("agent_security.network_profile", "DEFAULT_NETWORK_PROFILE"),
    "SUPPORTED_NETWORK_PROFILES": ("agent_security.network_profile", "SUPPORTED_NETWORK_PROFILES"),
    "TRUSTED_LOCAL_NETWORK_PROFILE": (
        "agent_security.network_profile",
        "TRUSTED_LOCAL_NETWORK_PROFILE",
    ),
    "NetworkProfile": ("agent_security.network_profile", "NetworkProfile"),
    "NetworkProfileError": ("agent_security.network_profile", "NetworkProfileError"),
    "NetworkProfileName": ("agent_security.network_profile", "NetworkProfileName"),
    "parse_network_profile": ("agent_security.network_profile", "parse_network_profile"),
    "resolve_effective_network_profile": (
        "agent_security.network_profile",
        "resolve_effective_network_profile",
    ),
    "ApprovalRequest": ("agent_security.policy", "ApprovalRequest"),
    "ApprovalRisk": ("agent_security.policy", "ApprovalRisk"),
    "LocalPolicyEngine": ("agent_security.policy", "LocalPolicyEngine"),
    "PolicyProfile": ("agent_security.policy", "PolicyProfile"),
    "build_approval_request": ("agent_security.policy", "build_approval_request"),
    "policy_profile": ("agent_security.policy", "policy_profile"),
    "InMemorySecretStore": ("agent_security.secret_store", "InMemorySecretStore"),
    "LocalSecretStore": ("agent_security.secret_store", "LocalSecretStore"),
    "SecretMaterial": ("agent_security.secret_store", "SecretMaterial"),
    "SecretMissingError": ("agent_security.secret_store", "SecretMissingError"),
    "SecretStore": ("agent_security.secret_store", "SecretStore"),
    "SecretStoreError": ("agent_security.secret_store", "SecretStoreError"),
    "SecretUnavailableError": ("agent_security.secret_store", "SecretUnavailableError"),
    "get_secret_value": ("agent_security.secret_store", "get_secret_value"),
    "SetupDownload": ("agent_security.setup_egress", "SetupDownload"),
    "SetupDownloadEvidence": ("agent_security.setup_egress", "SetupDownloadEvidence"),
    "SetupDownloadTransport": ("agent_security.setup_egress", "SetupDownloadTransport"),
    "SetupEgressError": ("agent_security.setup_egress", "SetupEgressError"),
    "SetupEgressGateway": ("agent_security.setup_egress", "SetupEgressGateway"),
    "TemporarySetupCredential": ("agent_security.setup_egress", "TemporarySetupCredential"),
    "DecodedHostGrant": ("agent_security.host_grant", "DecodedHostGrant"),
    "HostGrantAlgorithmError": ("agent_security.host_grant", "HostGrantAlgorithmError"),
    "HostGrantBindingError": ("agent_security.host_grant", "HostGrantBindingError"),
    "HostGrantSecurityError": ("agent_security.host_grant", "HostGrantSecurityError"),
    "HostGrantVerificationConfig": ("agent_security.host_grant", "HostGrantVerificationConfig"),
    "HostGrantVerifier": ("agent_security.host_grant", "HostGrantVerifier"),
    "JwtAlgorithm": ("agent_security.host_grant", "JwtAlgorithm"),
    "VerifiedHostGrant": ("agent_security.host_grant", "VerifiedHostGrant"),
    "CachingJwksKeyResolver": ("agent_security.jwt_adapter", "CachingJwksKeyResolver"),
    "DecodedJwtGrant": ("agent_security.jwt_adapter", "DecodedJwtGrant"),
    "HostGrantDecodeError": ("agent_security.jwt_adapter", "HostGrantDecodeError"),
    "JwksKeyResolver": ("agent_security.jwt_adapter", "JwksKeyResolver"),
    "PyJwtHostGrantDecoder": ("agent_security.jwt_adapter", "PyJwtHostGrantDecoder"),
}


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module 'agent_security' has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
