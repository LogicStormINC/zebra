"""Cloud input writes never call the local payload store or publish partial metadata."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_attachments import attachment_refs_from_event
from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.attachments import TextAttachmentInput
from agent_core.domain.events import EventType
from agent_core.domain.image_attachments import ImageAttachmentInput
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_storage.postgres.input_artifact_admission import persist_input_artifacts
from zebra_agent_api.cloud_attachment_ingress import prepare_cloud_inputs


def fixture():
    events = tuple(
        SessionBootstrapService()
        .build(
            SessionBootstrapCommand(
                title="Private input",
                user_input="Read my attachment",
                workspace_root=Path("/isolated"),
            )
        )
        .events
    )
    objects = Mock(spec=ArtifactObjectStorePort)
    objects.put_if_absent.side_effect = lambda r: ArtifactObjectReceipt(
        expectation=r.expectation,
        object_version="real-version-coordinate",
        verified_at=datetime.now(UTC),
    )
    inputs = (
        TextAttachmentInput(
            file_name="note.txt", media_type="text/plain", payload=b"private evidence"
        ),
        ImageAttachmentInput(
            file_name="pixel.png",
            media_type="image/png",
            payload=b"validated-by-ingress",
            width=1,
            height=1,
        ),
    )
    return events, objects, inputs


def test_distinct_object_events_retain_message_and_image_binding():
    events, objects, inputs = fixture()
    prepared, refs, records = prepare_cloud_inputs(objects, "qa", events, inputs)
    assert len(prepared) == len(events) + 2 and len(records) == len(refs) == 2
    assert objects.put_if_absent.call_count == 2
    user = next(e for e in prepared if e.event_type is EventType.USER_MESSAGE_RECEIVED)
    assert attachment_refs_from_event(user) == refs
    assert refs[1].image_width == 1 and refs[1].image_height == 1
    assert len({r.event_binding.event_id for r in records}) == 2
    assert [r.event_binding.sequence for r in records] == [e.sequence for e in prepared[-2:]]
    assert all(r.object_receipt.expectation.sha256 == r.reservation.sha256 for r in records)
    assert events[1].payload.get("attachments") is None
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {"epoch": "unused-by-mock"}
    persist_input_artifacts(connection, "qa", prepared, records)
    assert connection.execute.call_count == 3
    with pytest.raises(ValueError, match="complete unique batch"):
        persist_input_artifacts(connection, "qa", prepared, records[:1])
    with pytest.raises(ValueError, match="outside its exact"):
        persist_input_artifacts(connection, "foreign", prepared, records)


def test_failed_object_write_returns_no_admittable_batch():
    events, objects, inputs = fixture()
    first = objects.put_if_absent.side_effect
    count = 0

    def write(request):
        nonlocal count
        count += 1
        if count == 2:
            raise TimeoutError("object write outcome unknown")
        return first(request)

    objects.put_if_absent.side_effect = write
    with pytest.raises(TimeoutError):
        prepare_cloud_inputs(objects, "qa", events, inputs)
    assert all("attachments" not in e.payload for e in events)
    objects.delete_if_version.assert_not_called()  # Unknown writes never trigger blind deletion.


def test_empty_duplicate_and_batch_limits():
    events, objects, inputs = fixture()
    assert prepare_cloud_inputs(objects, "qa", events, ()) == (events, (), ())
    with pytest.raises(ValueError, match="duplicate"):
        prepare_cloud_inputs(objects, "qa", events, (inputs[0], inputs[0]))
    with pytest.raises(ValueError, match="bounded"):
        prepare_cloud_inputs(objects, "qa", events, inputs * 9)
    objects.put_if_absent.assert_not_called()
