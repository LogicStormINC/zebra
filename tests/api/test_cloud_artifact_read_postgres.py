from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.artifact_objects import ArtifactObjectExpectation, ArtifactObjectPutRequest
from agent_core.domain.cloud_artifact_requests import (
    ArtifactEventBinding,
    ArtifactFinalizeRequest,
    ArtifactRecordObjectRequest,
    ArtifactReserveRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_artifact_id
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_core.ports import WorkerMutationAuthority
from agent_storage import (
    CloudArtifactPayloadReader,
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresModelToolProjectionStore,
    PostgresSessionArtifactReadStore,
    S3ArtifactObjectStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    sqlite_control_plane_stores,
)
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.session import Session as BotocoreSession  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from zebra_agent_api import create_app, create_http_app

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
PAYLOAD = b"cloud postgres artifact\n"


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"artifact_read_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_api_composes_rebuildable_postgres_indexes_with_verified_object(
    dsn: str,
    tmp_path: Path,
) -> None:
    namespace = f"artifact-read-{uuid4()}"
    session = Session.create(title="Cloud Artifact", created_at=NOW)
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    events.append(_event(session, 0, EventType.SESSION_CREATED, {"title": session.title}))
    events.append(
        _event(
            session,
            1,
            EventType.MODEL_RESPONSE_RECEIVED,
            {
                "attempt_number": 1,
                "assistant_message": "token=super-secret " + "x" * 180,
                "tool_call_count": 1,
                "provider": "openai",
                "resolved_model": "gpt-test",
            },
        )
    )
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session.session_id,
        owner_instance_id="artifact-read-worker",
        ttl=timedelta(minutes=5),
    )
    metadata = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    objects = S3ArtifactObjectStore(_s3_client(), bucket=_bucket())
    reservation = ArtifactReserveRequest(
        artifact_id=new_artifact_id(),
        session_id=session.session_id,
        intended_event_sequence=2,
        kind="user_file",
        mime_type="text/plain",
        sha256=sha256(PAYLOAD).hexdigest(),
        size_bytes=len(PAYLOAD),
        idempotency_key=f"artifact-read-{uuid4()}",
        file_name="result.txt",
        created_at=NOW,
    )
    before_event = WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=session.session_id,
        expected_stream_revision=1,
        lease_fence=lease.fence,
    )
    metadata.reserve_for_worker(reservation, authority=before_event)
    receipt = objects.put_if_absent(
        ArtifactObjectPutRequest(
            expectation=ArtifactObjectExpectation(
                deployment_namespace=namespace,
                artifact_id=reservation.artifact_id,
                sha256=reservation.sha256,
                size_bytes=reservation.size_bytes,
            ),
            payload=PAYLOAD,
        )
    )
    metadata.record_object_for_worker(
        ArtifactRecordObjectRequest(
            artifact_id=reservation.artifact_id,
            session_id=session.session_id,
            expected_lifecycle_revision=0,
            idempotency_key="record-object",
            object_receipt=receipt,
        ),
        authority=before_event,
    )
    tool_event = _event(
        session,
        2,
        EventType.TOOL_EXECUTION_COMPLETED,
        {
            "attempt_number": 1,
            "tool_name": "tests.run",
            "status": "executed",
            "output": "api_key=do-not-leak",
            "metadata": {"artifact_uri": f"artifact://{reservation.artifact_id}"},
        },
    )
    events.append(tool_event)
    after_event = before_event.model_copy(update={"expected_stream_revision": 2})
    metadata.finalize_for_worker(
        ArtifactFinalizeRequest(
            artifact_id=reservation.artifact_id,
            session_id=session.session_id,
            expected_lifecycle_revision=1,
            idempotency_key="finalize",
            event_binding=ArtifactEventBinding(
                session_id=session.session_id,
                event_id=tool_event.event_id,
                sequence=tool_event.sequence,
                artifact_uri=f"artifact://{reservation.artifact_id}",
            ),
            object_receipt=receipt,
            finalized_at=NOW,
        ),
        authority=after_event,
    )

    projection_writer = PostgresModelToolProjectionStore(
        dsn,
        deployment_namespace=namespace,
    )
    assert projection_writer.replay_session(session.session_id) == 2
    artifacts = PostgresSessionArtifactReadStore(dsn, deployment_namespace=namespace)
    reader = CloudArtifactPayloadReader(
        metadata,
        objects,
        deployment_namespace=namespace,
    )
    local = sqlite_control_plane_stores(tmp_path / "api.db")
    local.sessions.save_session(session)
    local.workspaces.save_workspace(
        WorkspaceProjection(
            session_id=session.session_id,
            workspace_root="/tmp/cloud-artifact-read",
            prepared_at=NOW,
            updated_at=NOW,
            current_sequence=0,
            status=WorkspaceStatus.PREPARED,
            policy_profile="full_access",
        )
    )
    stores = replace(local, artifacts=artifacts, artifact_payload_reader=reader)
    api = create_app(tmp_path / "api.db", stores=stores)

    listed = api.get_session_artifacts(str(session.session_id))
    content = api.get_session_artifact_content(str(session.session_id), "tool-run:2")
    download = TestClient(
        create_http_app(tmp_path / "api.db", stores=stores)
    ).get(
        f"/tasks/{session.session_id}/artifacts/{reservation.artifact_id}/download"
    )

    assert listed.status_code == 200
    assert [item["artifact_id"] for item in listed.body["artifacts"]] == [
        "model-call:1",
        "tool-run:2",
    ]
    assert listed.body["artifacts"][0]["preview_state"] == {
        "redacted": True,
        "truncated": True,
    }
    assert listed.body["artifacts"][1]["preview"] == "api_key=[REDACTED]"
    assert listed.body["artifacts"][1]["lifecycle"]["status"] == "active"
    assert content.status_code == 200
    assert content.body["size_bytes"] == len(PAYLOAD)
    assert download.status_code == 200
    assert download.content == PAYLOAD
    assert download.headers["cache-control"] == "private, no-store"

    before_rebuild = listed.body["artifacts"]
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "DELETE FROM model_call_projections WHERE deployment_namespace = %s",
            (namespace,),
        )
        connection.execute(
            "DELETE FROM tool_run_projections WHERE deployment_namespace = %s",
            (namespace,),
        )
    assert artifacts.list_for_session(session.session_id) == []
    assert projection_writer.replay_session(session.session_id) == 2
    assert api.get_session_artifacts(str(session.session_id)).body["artifacts"] == before_rebuild

    other_namespace = PostgresSessionArtifactReadStore(
        dsn,
        deployment_namespace=f"other-{uuid4()}",
    )
    assert other_namespace.list_for_session(session.session_id) == []


def _event(
    session: Session,
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
) -> SessionEvent:
    return SessionEvent.create(
        session_id=session.session_id,
        sequence=sequence,
        event_type=event_type,
        actor=EventActor.HARNESS,
        payload=payload,
        created_at=NOW,
    )


def _s3_client() -> Any:
    endpoint = os.environ.get("ZEBRA_TEST_S3_ENDPOINT")
    access_key = os.environ.get("ZEBRA_TEST_S3_ACCESS_KEY")
    secret_key = os.environ.get("ZEBRA_TEST_S3_SECRET_KEY")
    if not endpoint or not access_key or not secret_key:
        pytest.skip("set ZEBRA_TEST_S3_* variables to run MinIO tests")
    return BotocoreSession().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _bucket() -> str:
    return os.environ.get("ZEBRA_TEST_S3_BUCKET", "zebra-artifacts")
