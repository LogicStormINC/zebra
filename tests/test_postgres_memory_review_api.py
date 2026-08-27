from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectVerification,
)
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import GovernedMemoryEntry
from agent_core.ports import ArtifactPayloadObjectReadPort, IdempotencyRecord
from agent_storage import (
    ControlPlaneStores,
    PostgresEventStore,
    PostgresIdempotencyStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    list_confirmed_repo_memories,
    postgres_control_plane_stores,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo
from zebra_agent_api import create_app
from zebra_agent_worker.cloud_memory_recovery import (
    MEMORY_RECOVERY_ACTION,
    memory_recovery_key,
)

from tests.agent_storage.governed_memory_test_support import (
    CURSOR_SIGNING_KEY,
    authority,
    candidate,
    management,
    plan,
    prepare_environment,
)


class _NoArtifactObjects(ArtifactPayloadObjectReadPort):
    def verify(self, expectation: ArtifactObjectExpectation) -> ArtifactObjectVerification:
        raise AssertionError(f"unexpected Artifact verify: {expectation.artifact_id}")

    def read_version_verified(
        self,
        expectation: ArtifactObjectExpectation,
        object_version: str,
    ) -> bytes:
        raise AssertionError(
            f"unexpected Artifact read: {expectation.artifact_id}@{object_version}"
        )


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def isolated_dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"api_memory_review_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield dsn
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_cloud_api_review_commits_atomically_and_is_recalled_by_next_task(
    isolated_dsn: str,
    tmp_path: Path,
) -> None:
    environment = prepare_environment(isolated_dsn)
    record = candidate(
        environment,
        text="Prefer focused PostgreSQL memory checks before the full gate.",
    )
    environment.store.commit_worker_candidates(
        plan(
            environment,
            operation_id="memory-api:candidate",
            expected_revision=1,
            records=(record,),
        ),
        authority=authority(environment, 1),
    )
    scope = OpaqueAuthorityScope(
        authority_issuer="https://memory-api.test",
        namespace_id="memory-api",
    )
    stores = postgres_control_plane_stores(
        isolated_dsn,
        deployment_namespace=environment.namespace,
        memory_cursor_signing_key=CURSOR_SIGNING_KEY,
        artifact_objects=_NoArtifactObjects(),
        history_scope=scope,
        continuation_scope=scope,
    )
    api = create_app(
        tmp_path / "must-not-be-created.sqlite",
        stores=cast(ControlPlaneStores, stores),
    )

    blocked = api.confirm_session_memory(
        str(environment.session_id),
        str(record.memory_id),
        {"operator": "api-reviewer", "reason": "explicit preference verified"},
    )
    assert blocked.status_code == 409
    assert blocked.body["status"] == "memory_review_conflict"
    blocked_record = stores.memories.get_authority(
        record.memory_id,
        management=management("inspect:blocked-api-review"),
    )
    assert isinstance(blocked_record, GovernedMemoryEntry)
    assert blocked_record.revision == 1
    assert blocked_record.record.status.value == "candidate"

    PostgresLeaseStore(
        isolated_dsn,
        deployment_namespace=environment.namespace,
    ).release(environment.session_id, fence=environment.lease.fence)

    response = api.confirm_session_memory(
        str(environment.session_id),
        str(record.memory_id),
        {"operator": "api-reviewer", "reason": "explicit preference verified"},
    )

    assert response.status_code == 200
    assert response.body["memory_status"] == "confirmed"
    assert response.body["event_type"] == EventType.MEMORY_REVIEW_RECORDED.value
    reviewed = stores.memories.get_authority(
        record.memory_id,
        management=management("inspect:api-review"),
    )
    assert isinstance(reviewed, GovernedMemoryEntry)
    assert reviewed.revision == 2
    assert reviewed.record.status.value == "confirmed"
    stored_session = stores.sessions.get_session(environment.session_id)
    stored_workspace = stores.workspaces.get_workspace(environment.session_id)
    assert stored_session is not None and stored_workspace is not None
    assert stored_session.current_sequence == stored_workspace.current_sequence == 3
    assert stores.events.list_for_session(environment.session_id)[-1].event_type is (
        EventType.MEMORY_REVIEW_RECORDED
    )

    recalled = list_confirmed_repo_memories(
        stores.memories,
        repo_id="zebra-agent",
        query_text="PostgreSQL checks",
    )
    assert [item.text for item in recalled] == [record.text]
    assert not (tmp_path / "must-not-be-created.sqlite").exists()


def test_postgres_memory_recovery_selection_is_oldest_first_and_receipted(
    isolated_dsn: str,
    tmp_path: Path,
) -> None:
    namespace = f"memory-recovery-{uuid4()}"
    bootstrap_control_plane_epoch(isolated_dsn, deployment_namespace=namespace)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Recover old Memory",
            user_input="preference: retain the durable recovery marker",
            workspace_root=tmp_path,
        )
    )
    started = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    )
    completed = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=started.sequence + 1,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "summary": "done", "metadata": {}},
    )
    events = [*bootstrap.events, started, completed]
    event_store = PostgresEventStore(isolated_dsn, deployment_namespace=namespace)
    for event in events:
        event_store.append(event)
    projections = PostgresProjectionStore(isolated_dsn, deployment_namespace=namespace)
    projections.save_session(rebuild_session(events))
    PostgresWorkspaceProjectionStore(
        isolated_dsn,
        deployment_namespace=namespace,
    ).save_workspace(rebuild_workspace(events))

    pending = projections.list_memory_recovery_sessions(
        limit=1,
        recovery_action=MEMORY_RECOVERY_ACTION,
    )
    assert [item.session_id for item in pending] == [bootstrap.session.session_id]

    PostgresIdempotencyStore(
        isolated_dsn,
        deployment_namespace=namespace,
    ).save(
        IdempotencyRecord(
            action=MEMORY_RECOVERY_ACTION,
            idempotency_key=memory_recovery_key(
                bootstrap.session.session_id,
                completed.sequence,
            ),
            request_hash="worker-memory-finalization-recovery-v1",
            status_code=204,
            response_body={"completion_revision": completed.sequence},
            created_at=datetime.now(UTC),
        )
    )
    assert projections.list_memory_recovery_sessions(
        limit=1,
        recovery_action=MEMORY_RECOVERY_ACTION,
    ) == []
