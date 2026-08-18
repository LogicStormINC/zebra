from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadLifecycleStatus,
    ArtifactPayloadWrite,
)
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports import (
    ArtifactPayloadReadInspection,
    ArtifactPayloadReadStatus,
)
from agent_storage import SQLiteToolRunStore, sqlite_control_plane_stores
from zebra_agent_api import create_app

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
ARTIFACT_ID = ArtifactId(UUID("00000000-0000-0000-0000-000000000001"))


class PayloadReaderStub:
    def __init__(
        self,
        status: ArtifactPayloadReadStatus,
        *,
        mime_type: str = "text/plain",
        bound_event_sequence: int | None = None,
    ) -> None:
        self.status = status
        self.mime_type = mime_type
        self.bound_event_sequence = bound_event_sequence
        self.inspect_count = 0
        self.read_count = 0

    def describe_payload(
        self,
        session_id: SessionId,
        uri: str,
    ) -> ArtifactPayloadReadInspection:
        artifact_id = ARTIFACT_ID
        return ArtifactPayloadReadInspection(
            artifact_id=artifact_id,
            session_id=session_id,
            mime_type=self.mime_type,
            status=self.status,
            lifecycle_status=(
                "active"
                if self.status is ArtifactPayloadReadStatus.AVAILABLE
                else "staged"
            ),
            bound_event_sequence=self.bound_event_sequence,
        )

    def inspect_payload(
        self,
        session_id: SessionId,
        uri: str,
    ) -> ArtifactPayloadReadInspection:
        self.inspect_count += 1
        return self.describe_payload(session_id, uri)

    def read_payload_bytes(self, session_id: SessionId, uri: str) -> bytes:
        self.read_count += 1
        return b"cloud payload"


def test_api_reads_content_through_injected_cloud_read_capability(tmp_path: Path) -> None:
    database_path = tmp_path / "api.db"
    stores = sqlite_control_plane_stores(database_path)
    session = stores.sessions.save_session(Session.create(title="cloud"))
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=1,
            tool_name="tests.run",
            status="executed",
            output="passed",
            artifact_uri=f"artifact://{ARTIFACT_ID}",
            created_at=NOW,
        )
    )
    cloud_stores = replace(
        stores,
        artifact_payload_reader=PayloadReaderStub(ArtifactPayloadReadStatus.AVAILABLE),
    )

    response = create_app(database_path, stores=cloud_stores).get_session_artifact_content(
        str(session.session_id),
        "tool-run:1",
    )

    assert response.status_code == 200
    assert response.body["content_base64"] == "Y2xvdWQgcGF5bG9hZA=="


def test_api_reports_nonfinalized_cloud_payload_as_unavailable(tmp_path: Path) -> None:
    database_path = tmp_path / "api.db"
    stores = sqlite_control_plane_stores(database_path)
    session = stores.sessions.save_session(Session.create(title="cloud"))
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=1,
            tool_name="tests.run",
            status="executed",
            output="passed",
            artifact_uri=f"artifact://{ARTIFACT_ID}",
            created_at=NOW,
        )
    )
    cloud_stores = replace(
        stores,
        artifact_payload_reader=PayloadReaderStub(ArtifactPayloadReadStatus.UNAVAILABLE),
    )

    response = create_app(database_path, stores=cloud_stores).get_session_artifact_content(
        str(session.session_id),
        "tool-run:1",
    )

    assert response.status_code == 409
    assert response.body["reason"] == "artifact_payload_unavailable"


def test_api_denies_sensitive_payload_before_object_inspection(tmp_path: Path) -> None:
    database_path = tmp_path / "api.db"
    stores = sqlite_control_plane_stores(database_path)
    session = stores.sessions.save_session(Session.create(title="cloud"))
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=1,
            tool_name="tests.run",
            status="executed",
            output="structured result",
            artifact_uri=f"artifact://{ARTIFACT_ID}",
            created_at=NOW,
        )
    )
    reader = PayloadReaderStub(
        ArtifactPayloadReadStatus.AVAILABLE,
        mime_type="application/json",
    )
    api = create_app(
        database_path,
        stores=replace(stores, artifact_payload_reader=reader),
    )

    response = api.get_session_artifact_content(str(session.session_id), "tool-run:1")

    assert response.status_code == 409
    assert response.body["status"] == "artifact_access_denied"
    assert reader.inspect_count == 0
    assert reader.read_count == 0


def test_api_rejects_payload_bound_to_another_tool_event(tmp_path: Path) -> None:
    database_path = tmp_path / "api.db"
    stores = sqlite_control_plane_stores(database_path)
    session = stores.sessions.save_session(Session.create(title="cloud"))
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=1,
            tool_name="tests.run",
            status="executed",
            output="passed",
            artifact_uri=f"artifact://{ARTIFACT_ID}",
            created_at=NOW,
        )
    )
    reader = PayloadReaderStub(
        ArtifactPayloadReadStatus.AVAILABLE,
        bound_event_sequence=2,
    )
    api = create_app(database_path, stores=replace(stores, artifact_payload_reader=reader))

    response = api.get_session_artifact_content(str(session.session_id), "tool-run:1")

    assert response.status_code == 409
    assert response.body["reason"] == "artifact_payload_unavailable"
    assert reader.read_count == 0


def test_cloud_reader_disables_legacy_prune_even_on_local_id_collision(tmp_path: Path) -> None:
    database_path = tmp_path / "api.db"
    stores = sqlite_control_plane_stores(database_path)
    session = stores.sessions.save_session(Session.create(title="cloud"))
    local_payload = stores.artifact_payloads.store_payload(
        ArtifactPayloadWrite(
            session_id=session.session_id,
            kind="tool-output",
            mime_type="text/plain",
            payload=b"local collision",
            created_at=NOW,
        ),
        artifact_id=ARTIFACT_ID,
    )
    SQLiteToolRunStore(database_path).upsert(
        ToolRunRecord(
            session_id=session.session_id,
            sequence=1,
            tool_name="tests.run",
            status="executed",
            output="passed",
            artifact_uri=local_payload.uri,
            created_at=NOW,
        )
    )
    api = create_app(
        database_path,
        stores=replace(
            stores,
            artifact_payload_reader=PayloadReaderStub(ArtifactPayloadReadStatus.AVAILABLE),
        ),
    )

    response = api.prune_session_artifact(str(session.session_id), "tool-run:1")

    assert response.status_code == 409
    assert response.body["reason"] == "cloud_artifact_prune_requires_management_transaction"
    persisted = stores.artifact_payloads.get_payload(ARTIFACT_ID)
    assert persisted is not None
    assert persisted.lifecycle_status is ArtifactPayloadLifecycleStatus.ACTIVE
