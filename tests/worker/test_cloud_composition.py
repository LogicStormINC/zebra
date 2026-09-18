from uuid import UUID

import pytest
from agent_core.domain.identifiers import ArtifactId
from zebra_agent_worker.cloud_composition import (
    _parse_workspace_snapshot_uri,
    _workspace_snapshot_uri,
)


def test_workspace_snapshot_uri_round_trips_artifact_identity() -> None:
    artifact_id = ArtifactId(UUID("11111111-1111-1111-1111-111111111111"))

    uri = _workspace_snapshot_uri(artifact_id, "a" * 64, 42, "version-7")

    assert _parse_workspace_snapshot_uri(uri) == (artifact_id, "a" * 64, 42, "version-7")


def test_workspace_snapshot_uri_rejects_legacy_shape_without_identity() -> None:
    with pytest.raises(ValueError, match="unsupported workspace object uri"):
        _parse_workspace_snapshot_uri("workspace-snapshot/a/42/version-7")
