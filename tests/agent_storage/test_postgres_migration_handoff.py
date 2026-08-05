from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import HandoffId, new_session_id
from agent_core.domain.session_handoff import (
    HandoffActorKind,
    HandoffOperationStatus,
    HandoffReason,
    SessionHandoffEnvelope,
    WorkspaceBindingRevision,
)
from agent_core.ports.session_handoff import (
    HandoffOperation,
    SessionHandoffCommitRequest,
    SessionHandoffCreateRequest,
)
from agent_storage import SQLiteEventStore
from agent_storage.postgres import (
    MigrationImportError,
    apply_postgres_migrations,
    export_sqlite_snapshot,
    import_sqlite_event_snapshot,
    write_sqlite_snapshot,
)
from agent_storage.session_handoff_events import build_handoff_events
from agent_storage.session_handoffs import SQLiteSessionHandoffStore
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"test_migration_handoff_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_event_import_replays_handoff_aggregate_and_rebuilt_lineage(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    SQLiteSessionHandoffStore(source)
    event_store = SQLiteEventStore(source)
    created_at = datetime(2026, 8, 5, tzinfo=UTC)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Handoff source", user_input="complete source",
            workspace_root=tmp_path, policy_profile="local-safe", created_at=created_at,
        )
    )
    source_id = bootstrap.session.session_id
    source_events = [
        *bootstrap.events,
        SessionEvent.create(
            session_id=source_id, sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED, actor=EventActor.HARNESS,
            payload={"attempt_number": 1}, created_at=created_at,
        ),
        SessionEvent.create(
            session_id=source_id, sequence=4,
            event_type=EventType.SESSION_COMPLETED, actor=EventActor.HARNESS,
            payload={"summary": "done"}, created_at=created_at,
        ),
    ]
    for event in source_events:
        event_store.append(event)
    target_id = new_session_id()
    handoff_id = HandoffId(UUID("00000000-0000-0000-0000-000000000701"))
    operation_id = UUID("00000000-0000-0000-0000-000000000702")
    workspace_revision = WorkspaceBindingRevision(
        workspace_id="/workspaces/handoff-import",
        revision_hash="workspace-revision", runtime_snapshot_id="snapshot-1",
    )
    create_request = SessionHandoffCreateRequest(
        source_session_id=source_id, idempotency_key="handoff-import-key",
        title="Handoff target", reason=HandoffReason.OPERATOR_HANDOFF,
        stage_prompt="continue the imported stage", principal_identity_hash="principal-hash",
        actor_kind=HandoffActorKind.OPERATOR,
    )
    operation = HandoffOperation(
        operation_id=str(operation_id), status=HandoffOperationStatus.PREPARING,
        source_session_id=source_id, target_session_id=target_id, handoff_id=handoff_id,
        idempotency_key_hash="1" * 64, request_hash="2" * 64,
        expected_source_stream_version=4, source_lease_fence=None,
        authority_revision="3" * 64, workspace_revision=workspace_revision,
        task_profile_revision="4" * 64, effective_depth_limit=8, artifact_id=None,
        created_at=created_at - timedelta(minutes=1), updated_at=created_at,
    )
    draft = SessionHandoffEnvelope(
        handoff_id=handoff_id, source_session_id=source_id, target_session_id=target_id,
        root_session_id=source_id, source_stage_index=0, target_stage_index=1,
        reason=create_request.reason, objective="resume the imported stage",
        immediate_next=create_request.stage_prompt,
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=4),
        source_event_hash="5" * 64, workspace_revision=workspace_revision,
        created_at=created_at, checksum="0" * 64,
    )
    envelope = draft.model_copy(update={"checksum": draft.expected_checksum()})
    artifact_id = "handoff-artifact-1"
    request = SessionHandoffCommitRequest(
        operation=operation, create_request=create_request,
        envelope=envelope, artifact_id=artifact_id,
    )
    workspace: dict[str, object] = {
        "workspace_root": "/workspaces/handoff-import", "policy_profile": "local-safe",
        "tool_profile": "general", "network_profile": "none", "network_allowlist": [],
        "mcp_allowlist": None, "skill_components": None,
    }
    for event in build_handoff_events(operation, request, workspace):
        event_store.append(event)
    with sqlite3.connect(source) as connection:
        connection.execute(
            """INSERT INTO handoff_operations VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                str(operation_id), "committed", str(source_id), str(target_id), str(handoff_id),
                operation.idempotency_key_hash, operation.request_hash,
                operation.expected_source_stream_version, None, None, None,
                operation.authority_revision, workspace_revision.model_dump_json(),
                operation.task_profile_revision, operation.effective_depth_limit, artifact_id,
                operation.created_at.isoformat(), envelope.created_at.isoformat(), None,
            ),
        )
        connection.execute(
            "INSERT INTO session_handoff_envelopes VALUES (?, ?, ?, ?, ?, ?)",
            (str(handoff_id), str(source_id), str(target_id), artifact_id,
             envelope.model_dump_json(), envelope.checksum),
        )
        connection.executemany(
            "INSERT INTO session_lineage VALUES (?, ?, ?, ?, ?)",
            ((str(source_id), str(source_id), None, None, 0),
             (str(target_id), str(source_id), str(source_id), str(handoff_id), 1)),
        )
        connection.execute(
            "INSERT INTO handoff_dispatch_outbox VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(target_id), str(target_id), str(handoff_id), "pending", None, None, None,
             None, None, None, envelope.created_at.isoformat()),
        )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(
            source,
            table_names=(
                "session_events", "handoff_operations", "session_handoff_envelopes",
                "session_lineage", "handoff_dispatch_outbox",
            ),
        ),
        snapshot_dir,
    )
    report = import_sqlite_event_snapshot(
        snapshot_dir, isolated_dsn, deployment_namespace="tenant-a",
        importer_identity="zebra-postgres-migration-v1",
    )
    assert report.handoff_operation_count == 1
    assert report.handoff_envelope_count == 1
    assert report.handoff_dispatch_count == 1
    assert report.handoff_lineage_count == 2
    with psycopg.connect(isolated_dsn) as connection:
        counts = connection.execute(
            """SELECT (SELECT count(*) FROM handoff_operations),
                (SELECT count(*) FROM session_handoff_envelopes),
                (SELECT count(*) FROM handoff_dispatch_outbox),
                (SELECT count(*) FROM execution_segments)"""
        ).fetchone()
        assert counts == (1, 1, 1, 2)
        assert connection.execute(
            "SELECT status, artifact_id FROM handoff_operations"
        ).fetchone() == ("committed", artifact_id)


def test_event_import_rejects_acked_handoff_dispatch_without_ack_timestamp(
    isolated_dsn: str, tmp_path: Path
) -> None:
    source = tmp_path / "source.sqlite"
    SQLiteSessionHandoffStore(source)
    with sqlite3.connect(source) as connection:
        connection.execute(
            "INSERT INTO handoff_dispatch_outbox VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), str(uuid4()), str(uuid4()), "acked", None, None, None, None,
             None, None, datetime(2026, 8, 5, tzinfo=UTC).isoformat()),
        )
    snapshot_dir = tmp_path / "snapshot"
    write_sqlite_snapshot(
        export_sqlite_snapshot(source, table_names=("handoff_dispatch_outbox",)),
        snapshot_dir,
    )
    with pytest.raises(MigrationImportError, match="ACK timestamp"):
        import_sqlite_event_snapshot(
            snapshot_dir, isolated_dsn, deployment_namespace="tenant-a",
            importer_identity="zebra-postgres-migration-v1",
        )
    with psycopg.connect(isolated_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM handoff_dispatch_outbox"
        ).fetchone() == (0,)
