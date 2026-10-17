"""Public aliases stay compatible; SSRF-only child imports avoid policy/JWT boot."""

import importlib
import json
import subprocess
import sys


def test_ssrf_import_does_not_initialize_unrelated_security_components():
    code = """
import sys
from agent_security.ssrf import resolve_and_validate
assert "agent_security.policy" not in sys.modules
assert "agent_security.jwt_adapter" not in sys.modules
assert "agent_security.host_grant" not in sys.modules
assert "jwt" not in sys.modules
assert str(resolve_and_validate("example.com", resolver=lambda _: ("1.1.1.1",))[0]) == "1.1.1.1"
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_existing_named_aliases_and_star_exports_remain_compatible():
    import agent_security

    expected = json.loads(ALIASES)
    for module, names in expected.items():
        source = importlib.import_module("agent_security." + module)
        for name in names:
            assert getattr(agent_security, name) is getattr(source, name)
            assert name in dir(agent_security)
    assert agent_security.__all__ == [
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
    assert not hasattr(agent_security, "unknown_security_export")


# Frozen current import aliases, including names outside the historical final __all__.
ALIASES = r"""
{
  "artifact_access": [
    "classify_artifact_access",
    "required_policy_profile_for_artifact_access"
  ],
  "artifact_access_audit": [
    "build_artifact_access_audit_metadata"
  ],
  "artifact_access_projection": [
    "ArtifactAccessProjection",
    "build_artifact_access_projection",
    "policy_rank",
    "serialize_artifact_access_projection"
  ],
  "artifact_control_audit": [
    "build_artifact_control_audit_metadata"
  ],
  "artifact_retention": [
    "EXTENDED_ARTIFACT_RETENTION",
    "SHORT_LIVED_ARTIFACT_RETENTION",
    "STANDARD_ARTIFACT_RETENTION",
    "resolve_artifact_retained_until",
    "resolve_artifact_retention_policy"
  ],
  "broker": [
    "CredentialBroker",
    "CredentialBrokerError",
    "CredentialDeniedError",
    "CredentialMissingError",
    "CredentialTransportError",
    "CredentialUnavailableError",
    "InMemoryCredentialBroker"
  ],
  "capabilities": [
    "CredentialCapability"
  ],
  "credentials": [
    "REDACTED_SECRET",
    "ScmCredentialBoundary",
    "ScmCredentialCapability",
    "ScmCredentialSettings"
  ],
  "delivery": [
    "CommitPolicy",
    "DeliveryDecision",
    "DeliveryDecisionType",
    "PullRequestPolicy"
  ],
  "environment_broker": [
    "EnvironmentCredentialBinding",
    "EnvironmentCredentialBroker"
  ],
  "mcp_proxy_policy": [
    "ToolEgressMetadata",
    "ToolEgressRoute",
    "classify_tool_egress"
  ],
  "network_profile": [
    "DEFAULT_NETWORK_PROFILE",
    "SUPPORTED_NETWORK_PROFILES",
    "TRUSTED_LOCAL_NETWORK_PROFILE",
    "NetworkProfile",
    "NetworkProfileError",
    "NetworkProfileName",
    "parse_network_profile",
    "resolve_effective_network_profile"
  ],
  "policy": [
    "ApprovalRequest",
    "ApprovalRisk",
    "LocalPolicyEngine",
    "PolicyProfile",
    "build_approval_request",
    "policy_profile"
  ],
  "secret_store": [
    "InMemorySecretStore",
    "LocalSecretStore",
    "SecretMaterial",
    "SecretMissingError",
    "SecretStore",
    "SecretStoreError",
    "SecretUnavailableError",
    "get_secret_value"
  ],
  "setup_egress": [
    "SetupDownload",
    "SetupDownloadEvidence",
    "SetupDownloadTransport",
    "SetupEgressError",
    "SetupEgressGateway",
    "TemporarySetupCredential"
  ],
  "host_grant": [
    "DecodedHostGrant",
    "HostGrantAlgorithmError",
    "HostGrantBindingError",
    "HostGrantSecurityError",
    "HostGrantVerificationConfig",
    "HostGrantVerifier",
    "JwtAlgorithm",
    "VerifiedHostGrant"
  ],
  "jwt_adapter": [
    "CachingJwksKeyResolver",
    "DecodedJwtGrant",
    "HostGrantDecodeError",
    "JwksKeyResolver",
    "PyJwtHostGrantDecoder"
  ]
}
"""
