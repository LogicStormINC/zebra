from datetime import UTC, datetime

from agent_core.domain import ArtifactRetentionProfile
from agent_security import (
    PolicyProfile,
    policy_profile,
    resolve_artifact_retained_until,
    resolve_artifact_retention_policy,
)


def test_bootstrap_profile_maps_to_extended_artifact_retention() -> None:
    policy = resolve_artifact_retention_policy(policy_profile())

    assert policy.profile is ArtifactRetentionProfile.EXTENDED


def test_read_only_profile_maps_to_extended_artifact_retention() -> None:
    policy = resolve_artifact_retention_policy(PolicyProfile.READ_ONLY.value)

    assert policy.profile is ArtifactRetentionProfile.EXTENDED


def test_workspace_write_profile_maps_to_standard_artifact_retention() -> None:
    policy = resolve_artifact_retention_policy(PolicyProfile.WORKSPACE_WRITE.value)

    assert policy.profile is ArtifactRetentionProfile.STANDARD


def test_full_access_profile_maps_to_short_lived_artifact_retention() -> None:
    policy = resolve_artifact_retention_policy(PolicyProfile.FULL_ACCESS.value)

    assert policy.profile is ArtifactRetentionProfile.SHORT_LIVED


def test_unknown_policy_profile_fails_closed_to_short_lived_artifact_retention() -> None:
    policy = resolve_artifact_retention_policy("unknown-profile")

    assert policy.profile is ArtifactRetentionProfile.SHORT_LIVED


def test_retained_until_resolution_uses_policy_profile_default_ttl() -> None:
    retained_until = resolve_artifact_retained_until(
        datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
        PolicyProfile.WORKSPACE_WRITE.value,
    )

    assert retained_until == datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
