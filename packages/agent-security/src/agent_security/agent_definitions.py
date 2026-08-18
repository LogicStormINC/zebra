"""Publication and ingress trust policy for Agent Definitions (AGENT-DEF-TRUST-01).

Content trust never grants capability: a Definition snapshot is a resolved
identity ceiling, not a grant. Publisher grant, Definition snapshot and Attempt
authority stay independently traced, and cross-issuer/namespace, prompt
injection and reference substitution all fail closed.
"""

from __future__ import annotations

from agent_core.application.agent_definitions import PublisherGrantCeiling
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot


class DefinitionTrustError(ValueError):
    """Raised when Definition content or scope violates the trust policy."""


class CrossScopeDefinitionError(DefinitionTrustError):
    """Raised when Definition scope does not match the caller's authority."""


class DefinitionReferenceSubstitutionError(DefinitionTrustError):
    """Raised when snapshot references do not match the bound Version identity."""


class DefinitionGrantEscalationError(DefinitionTrustError):
    """Raised when Definition content attempts to grant execution capability."""


def assert_snapshot_grants_nothing(
    snapshot: AgentDefinitionSnapshot,
) -> None:
    """Content trust: the snapshot declares identities, never grants.

    The snapshot carries resolved policy/tool/Skill references and digests; it
    does not by itself enable tools, network, Memory writes or publication.
    Callers must treat it as a ceiling that still requires Zebra Policy,
    Approval and Sandbox narrowing.
    """
    for reference in (
        snapshot.model_policy_ref,
        snapshot.tool_profile_ref,
        snapshot.memory_policy_ref,
        snapshot.security_policy_ref,
        snapshot.evaluation_profile_ref,
        snapshot.runtime_profile_ref,
    ):
        lowered = reference.lower()
        if any(
            marker in lowered
            for marker in (
                "grant",
                "approve",
                "bypass",
                "allow-all",
                "unrestricted",
            )
        ):
            raise DefinitionGrantEscalationError(
                f"Definition reference {reference!r} must not grant capability"
            )


def assert_scope_authority(
    scope_namespace_id: str,
    ceiling: PublisherGrantCeiling | None,
) -> None:
    """Cross-issuer/namespace access fails closed."""
    if ceiling is None:
        raise CrossScopeDefinitionError("missing publisher grant; failing closed")
    if ceiling.namespace_id != scope_namespace_id:
        raise CrossScopeDefinitionError(
            "Definition scope namespace is outside the publisher grant"
        )


def assert_no_reference_substitution(
    snapshot: AgentDefinitionSnapshot,
    *,
    version_digest: str,
) -> None:
    """The snapshot must bind the exact immutable Version identity."""
    if snapshot.definition_digest != version_digest:
        raise DefinitionReferenceSubstitutionError(
            "snapshot references a different Version digest; failing closed"
        )


def assert_no_injected_content(
    snapshot: AgentDefinitionSnapshot,
) -> None:
    """Prompt-injection markers in Definition metadata fail closed.

    Definition name/description and component references are data, never
    instructions; any marker that could steer a downstream model or tool is
    rejected at ingress rather than carried into execution.
    """
    scan_text = " ".join(
        (
            snapshot.definition_id and str(snapshot.definition_id) or "",
            snapshot.authority_issuer,
            snapshot.namespace_id,
            snapshot.model_policy_ref,
            snapshot.tool_profile_ref,
            snapshot.memory_policy_ref,
            snapshot.security_policy_ref,
            snapshot.evaluation_profile_ref,
            snapshot.runtime_profile_ref,
        )
    ).lower()
    scan_text = scan_text.replace("-", " ").replace("_", " ")
    markers = (
        "ignore previous instructions",
        "system prompt",
        "tool grant",
        "elevate privileges",
        "override policy",
        "do not follow",
    )
    if any(marker in scan_text for marker in markers):
        raise DefinitionGrantEscalationError(
            "Definition content contains injection markers; failing closed"
        )
