"""Runnable real PG/S3 input gate; dedicated QA DSN/bucket required, no Worker/provider."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.attachments import TextAttachmentInput
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.turns import InteractionMode
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import cloud_composition_from_environment, postgres_control_plane_stores
from agent_storage.event_rows import SessionEventSequenceConflictError
from agent_storage.postgres.epoch import bootstrap_control_plane_epoch
from agent_storage.postgres.input_artifact_admission import append_input_message
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from zebra_agent_api.cloud_attachment_ingress import prepare_cloud_inputs


def main():
    cloud = cloud_composition_from_environment()
    if "native-db" not in cloud.dsn or os.environ.get("ZEBRA_S3_BUCKET") != "erp-full-qa":
        raise ValueError("dedicated isolated QA PostgreSQL and object bucket required")
    namespace = "input-qa-" + uuid4().hex
    bootstrap_control_plane_epoch(cloud.dsn, deployment_namespace=namespace)
    stores = postgres_control_plane_stores(
        cloud.dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Atomic private inputs",
            user_input="Read the isolated files",
            workspace_root=Path("/isolated"),
            interaction_mode=InteractionMode.CONVERSATION,
        )
    )
    items = tuple(
        TextAttachmentInput(
            file_name=f"qa-{i}.txt", media_type="text/plain", payload=f"private QA {i}".encode()
        )
        for i in range(2)
    )
    events, refs, records = prepare_cloud_inputs(
        cloud.artifact_objects, namespace, tuple(bootstrap.events), items
    )
    request = TaskAdmissionRequest(
        events=events,
        session=rebuild_session(list(events)),
        workspace=rebuild_workspace(list(events)),
        input_artifacts=records,
    )
    admission = PostgresTaskAdmissionTransaction(cloud.dsn, deployment_namespace=namespace)
    # Exact batch mismatch fails after event writes, proving the surrounding
    # native transaction rolls those writes and metadata back together.
    try:
        admission.admit(replace(request, input_artifacts=records[:1]))
    except ValueError:
        pass
    else:
        raise AssertionError("partial input metadata accepted")
    with psycopg.connect(cloud.dsn) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM session_streams WHERE deployment_namespace=%s", (namespace,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM artifact_payload_metadata WHERE deployment_namespace=%s",
                (namespace,),
            ).fetchone()[0]
            == 0
        )
    receipt = admission.admit(request)
    assert receipt.event_count == len(events)
    for item, ref in zip(items, refs, strict=True):
        actual = stores.artifact_payload_reader.read_payload_bytes(
            bootstrap.session.session_id, f"artifact://{ref.attachment_id}"
        )
        assert actual == item.payload and sha256(actual).hexdigest() == ref.sha256
        try:
            stores.artifact_payload_reader.read_payload_bytes(
                SessionId(uuid4()), f"artifact://{ref.attachment_id}"
            )
        except (ValueError, FileNotFoundError, RuntimeError):
            pass
        else:
            raise AssertionError("foreign Session read admitted")
    session = request.session
    message = SessionEvent.create(
        session_id=session.session_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        created_at=datetime.now(UTC),
        payload={"content": "Another private file"},
    )
    follow, follow_refs, follow_records = prepare_cloud_inputs(
        cloud.artifact_objects,
        namespace,
        (message,),
        (
            TextAttachmentInput(
                file_name="follow.txt", media_type="text/plain", payload=b"follow-up"
            ),
        ),
    )
    updated = append_input_message(cloud.dsn, namespace, session, follow, follow_records)
    assert updated.current_sequence == follow[-1].sequence
    before = stores.events.list_for_session(session.session_id)
    try:
        append_input_message(cloud.dsn, namespace, session, follow, follow_records)
    except SessionEventSequenceConflictError:
        pass
    else:
        raise AssertionError("stale message CAS accepted")
    assert stores.events.list_for_session(session.session_id) == before
    assert (
        stores.artifact_payload_reader.read_payload_bytes(
            session.session_id, f"artifact://{follow_refs[0].attachment_id}"
        )
        == b"follow-up"
    )
    with psycopg.connect(cloud.dsn) as connection:
        rows = connection.execute(
            "SELECT lifecycle_status,reservation_owner_instance_id "
            "FROM artifact_payload_metadata WHERE deployment_namespace=%s",
            (namespace,),
        ).fetchall()
        assert len(rows) == 3 and all(
            row[0] == "finalized" and row[1].startswith("api-input:") for row in rows
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM session_events WHERE deployment_namespace=%s "
                "AND event_type='model_request_started'",
                (namespace,),
            ).fetchone()[0]
            == 0
        )
    result = dict(
        stage="real_cloud_input_gate",
        namespace=namespace,
        checks=[
            "whole admission rollback",
            "multiple exact S3 reads",
            "foreign Session denied",
            "follow-up atomic input",
            "stale CAS refused without duplicate",
            "explicit API epoch/revision provenance",
        ],
        model_calls=0,
        search_calls=0,
    )
    Path("/evidence/input-gate.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
