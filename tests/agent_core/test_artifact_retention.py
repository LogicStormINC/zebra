from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain import ArtifactRetentionPolicy, ArtifactRetentionProfile


def test_artifact_retention_policy_requires_positive_ttl() -> None:
    with pytest.raises(ValueError, match="ttl must be positive"):
        ArtifactRetentionPolicy(
            profile=ArtifactRetentionProfile.STANDARD,
            ttl=timedelta(0),
        )


def test_artifact_retention_policy_computes_retained_until_in_utc() -> None:
    policy = ArtifactRetentionPolicy(
        profile=ArtifactRetentionProfile.SHORT_LIVED,
        ttl=timedelta(days=1),
    )

    retained_until = policy.retained_until_for(
        datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )

    assert retained_until == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_artifact_retention_policy_requires_timezone_aware_created_at() -> None:
    policy = ArtifactRetentionPolicy(
        profile=ArtifactRetentionProfile.EXTENDED,
        ttl=timedelta(days=30),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        policy.retained_until_for(datetime(2026, 6, 30, 12, 0))
