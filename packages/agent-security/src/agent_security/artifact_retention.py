from datetime import datetime, timedelta

from agent_core.domain import ArtifactRetentionPolicy, ArtifactRetentionProfile

from agent_security.policy import PolicyProfile, policy_profile

SHORT_LIVED_ARTIFACT_RETENTION = ArtifactRetentionPolicy(
    profile=ArtifactRetentionProfile.SHORT_LIVED,
    ttl=timedelta(days=1),
)
STANDARD_ARTIFACT_RETENTION = ArtifactRetentionPolicy(
    profile=ArtifactRetentionProfile.STANDARD,
    ttl=timedelta(days=7),
)
EXTENDED_ARTIFACT_RETENTION = ArtifactRetentionPolicy(
    profile=ArtifactRetentionProfile.EXTENDED,
    ttl=timedelta(days=30),
)

_RETENTION_BY_POLICY_PROFILE = {
    "": SHORT_LIVED_ARTIFACT_RETENTION,
    policy_profile(): EXTENDED_ARTIFACT_RETENTION,
    PolicyProfile.READ_ONLY.value: EXTENDED_ARTIFACT_RETENTION,
    PolicyProfile.WORKSPACE_WRITE.value: STANDARD_ARTIFACT_RETENTION,
    PolicyProfile.FULL_ACCESS.value: SHORT_LIVED_ARTIFACT_RETENTION,
}


def resolve_artifact_retention_policy(
    policy_profile_name: str | None,
) -> ArtifactRetentionPolicy:
    normalized = (policy_profile_name or "").strip()
    return _RETENTION_BY_POLICY_PROFILE.get(
        normalized,
        SHORT_LIVED_ARTIFACT_RETENTION,
    )


def resolve_artifact_retained_until(
    created_at: datetime,
    policy_profile_name: str | None,
) -> datetime:
    return resolve_artifact_retention_policy(policy_profile_name).retained_until_for(
        created_at
    )
