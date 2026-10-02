from typing import cast

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_session_id
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_core.ports.cloud_artifact_payload_store import CloudArtifactPayloadStorePort
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator


class RecordingDrafts:
    def __init__(self) -> None:
        self.drafts: list[HarnessEventDraft] = []

    def append_draft(self, draft: HarnessEventDraft) -> HarnessEventDraft:
        self.drafts.append(draft)
        return draft


def test_existing_artifact_read_reference_does_not_require_new_capture() -> None:
    coordinator = CloudToolOutputArtifactCoordinator(
        new_session_id(),
        cast(CloudArtifactPayloadStorePort, object()),
        cast(ArtifactObjectStorePort, object()),
    )
    uri = coordinator.capture_file(b"<svg/>", "comparison.svg", "image/svg+xml")
    coordinator.release_pending(uri)  # The publish event has already finalized the payload.
    draft = HarnessEventDraft(
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "tool_name": "artifacts.read",
            "status": "executed",
            "output": "<svg/>",
            "metadata": {"artifact_uri": uri},
        },
    )
    recorder = RecordingDrafts()

    assert coordinator.append_draft(draft, cast(DurableHarnessEventRecorder, recorder)) == draft
    assert recorder.drafts == [draft]
