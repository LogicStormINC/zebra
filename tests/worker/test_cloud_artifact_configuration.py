from pathlib import Path
from typing import Any, cast

import pytest
from zebra_agent_worker.execution import SessionExecutionService
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator


def _factory(_session_id: object) -> CloudToolOutputArtifactCoordinator:
    return cast(CloudToolOutputArtifactCoordinator, object())


def test_cloud_artifact_output_requires_fenced_projection_transaction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="fenced Worker projection transaction"):
        SessionExecutionService(
            database_path=tmp_path / "sessions.sqlite",
            claim_service=cast(Any, object()),
            resume_service=cast(Any, object()),
            deployment_namespace="cloud-test",
            cloud_artifact_factory=_factory,
        )


def test_cloud_artifact_output_rejects_dispatch_without_atomic_payload_linkage(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="requires atomic payload linkage"):
        SessionExecutionService(
            database_path=tmp_path / "sessions.sqlite",
            claim_service=cast(Any, object()),
            resume_service=cast(Any, object()),
            effect_dispatch=cast(Any, object()),
            worker_projection_transaction=cast(Any, object()),
            deployment_namespace="cloud-test",
            cloud_artifact_factory=_factory,
        )


def test_cloud_artifact_output_accepts_payload_aware_effect_dispatch(tmp_path: Path) -> None:
    class PayloadAwareDispatch:
        schedule_with_payload = staticmethod(lambda *args, **kwargs: None)
        complete_with_payload = staticmethod(lambda *args, **kwargs: None)
        mark_uncertain_with_payload = staticmethod(lambda *args, **kwargs: None)

    service = SessionExecutionService(
        database_path=tmp_path / "sessions.sqlite",
        claim_service=cast(Any, object()),
        resume_service=cast(Any, object()),
        effect_dispatch=cast(Any, PayloadAwareDispatch()),
        worker_projection_transaction=cast(Any, object()),
        deployment_namespace="cloud-test",
        cloud_artifact_factory=_factory,
    )

    assert service is not None
