"""AGENT-DEF-MEM-01 contract matrix: Definition-scoped governed Memory."""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionPlanner,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import GovernedMemoryEntry
from agent_core.domain.identifiers import AgentDefinitionId, MemoryId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import (
    PostgresLeaseStore,
    apply_postgres_migrations,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.agent_storage.governed_memory_test_support import NOW
from tests.agent_storage.governed_memory_test_support import (
    MemoryEnvironment as _MemoryEnvironment,
)
from tests.agent_storage.governed_memory_test_support import (
    authority as _authority,
)
from tests.agent_storage.governed_memory_test_support import (
    candidate as _candidate,
)
from tests.agent_storage.governed_memory_test_support import (
    plan as _plan,
)
from tests.agent_storage.governed_memory_test_support import (
    prepare_environment as _prepare_environment,
)

ISSUER = "https://issuer.example"
DEFINITION_ID = AgentDefinitionId(UUID("10000000-0000-0000-0000-000000000001"))


def _definition_scope() -> dict[str, object]:
    return {
        "authority_issuer": ISSUER,
        "namespace_id": "tenant-a",
        "definition_id": DEFINITION_ID,
    }


def _scoped_candidate(
    environment: _MemoryEnvironment,
    text: str = "Definition-scoped memory.",
) -> MemoryRecord:
    legacy = _candidate(
        environment,
        text=text,
        memory_type=MemoryType.PROCEDURE,
    )
    return legacy.model_copy(
        update={
            **_definition_scope(),
            "tenant_id": None,
            "user_id": None,
            "repo_id": None,
        }
    )





def _completed_session() -> Session:
    from agent_core.domain.sessions import Session, new_session_id

    return Session(
        session_id=new_session_id(),
        title="memory contract",
        status=SessionStatus.COMPLETED,
        current_sequence=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _preference_event(session: Session, content: str) -> SessionEvent:
    return SessionEvent.create(
        session_id=session.session_id,
        sequence=0,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": content},
        created_at=NOW,
    )


def test_scope_requires_all_three_fields() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="together"):
        MemoryRecord(
            memory_id=MemoryId(uuid4()),
            memory_type=MemoryType.PREFERENCE,
            text="x",
            confidence=0.9,
            visibility=MemoryVisibility.REPO,
            authority_issuer=ISSUER,
            created_at=now,
            updated_at=now,
        )
    with pytest.raises(ValueError, match="together"):
        MemoryQuery(
            authority_issuer=ISSUER,
            definition_id=DEFINITION_ID,
        )


def test_planner_propagates_definition_scope_and_drops_legacy_scope() -> None:
    session = _completed_session()
    plan = MemoryCandidateExtractionPlanner().plan(
        session=session,
        events=[_preference_event(session, "preference: use the canonical API")],
        next_sequence=1,
        command=MemoryCandidateExtractionCommand(
            repo_id="/workspaces/repo",
            extracted_at=NOW,
            **_definition_scope(),
        ),
    )
    assert plan.records
    for record in plan.records:
        assert record.authority_issuer == ISSUER
        assert record.namespace_id == "tenant-a"
        assert record.definition_id == DEFINITION_ID
        assert record.repo_id is None
        assert record.tenant_id is None
        assert record.user_id is None


def test_legacy_command_keeps_legacy_scope() -> None:
    session = _completed_session()
    plan = MemoryCandidateExtractionPlanner().plan(
        session=session,
        events=[_preference_event(session, "preference: keep the legacy scope")],
        next_sequence=1,
        command=MemoryCandidateExtractionCommand(
            repo_id="/workspaces/repo",
            extracted_at=NOW,
        ),
    )
    assert plan.records
    for record in plan.records:
        assert record.repo_id == "/workspaces/repo"
        assert record.authority_issuer is None
        assert record.definition_id is None


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"definition_memory_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def memory_environment(dsn: str) -> _MemoryEnvironment:
    return _prepare_environment(dsn)


def test_definition_scoped_commit_isolates_from_legacy_rows(
    memory_environment: _MemoryEnvironment,
) -> None:
    store = memory_environment.store
    legacy = _candidate(memory_environment, text="Legacy tenant memory.")
    store.commit_worker_candidates(
        _plan(
            memory_environment,
            operation_id="memory:legacy",
            expected_revision=1,
            records=(legacy,),
        ),
        authority=_authority(memory_environment, 1),
    )
    scoped = _scoped_candidate(memory_environment)
    store.commit_worker_candidates(
        _plan(
            memory_environment,
            operation_id="memory:scoped",
            expected_revision=2,
            records=(scoped,),
        ),
        authority=_authority(memory_environment, 2),
    )
    stored = store.list_for_worker(
        MemoryQuery(
            authority_issuer=ISSUER,
            namespace_id="tenant-a",
            definition_id=DEFINITION_ID,
            statuses=(MemoryStatus.CANDIDATE, MemoryStatus.CONFIRMED),
        ),
        authority=_authority(memory_environment, 3),
    )
    assert [entry.record.memory_id for entry in stored] == [scoped.memory_id]
    entry = stored[0]
    assert entry.record.authority_issuer == ISSUER
    assert entry.record.namespace_id == "tenant-a"
    assert entry.record.definition_id == DEFINITION_ID
    assert entry.record.tenant_id is None
    assert entry.record.repo_id is None
    legacy_readback = store.list_for_worker(
        MemoryQuery(
            repo_id="zebra-agent",
            visibility=MemoryVisibility.REPO,
            statuses=(MemoryStatus.CANDIDATE, MemoryStatus.CONFIRMED),
        ),
        authority=_authority(memory_environment, 3),
    )
    assert any(entry.record.memory_id == legacy.memory_id for entry in legacy_readback)
    assert all(entry.record.definition_id is None for entry in legacy_readback)


def test_supersede_preserves_definition_scope(
    memory_environment: _MemoryEnvironment,
) -> None:
    from agent_core.domain.governed_memory_operations import (
        AdministrativeMemoryReviewRequest,
        GovernedMemoryReviewAction,
    )
    from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS

    store = memory_environment.store
    first = _scoped_candidate(memory_environment)
    store.commit_worker_candidates(
        _plan(
            memory_environment,
            operation_id="memory:first",
            expected_revision=1,
            records=(first,),
        ),
        authority=_authority(memory_environment, 1),
    )
    store.commit_worker_candidates(
        _plan(
            memory_environment,
            operation_id="memory:promote-first",
            expected_revision=2,
            records=(first,),
            confirmed=(first.memory_id,),
        ),
        authority=_authority(memory_environment, 2),
    )
    second = _scoped_candidate(
        memory_environment,
        text="Replacement definition-scoped memory.",
    )
    store.commit_worker_candidates(
        _plan(
            memory_environment,
            operation_id="memory:second",
            expected_revision=4,
            records=(second,),
        ),
        authority=_authority(memory_environment, 4),
    )
    PostgresLeaseStore(
        memory_environment.dsn,
        deployment_namespace=memory_environment.namespace,
    ).release(memory_environment.session_id, fence=memory_environment.lease.fence)
    request = AdministrativeMemoryReviewRequest.create(
        deployment_namespace=memory_environment.namespace,
        operation_id="memory:review-supersede",
        session_id=memory_environment.session_id,
        expected_stream_revision=5,
        memory_id=second.memory_id,
        expected_revision=1,
        action=GovernedMemoryReviewAction.CONFIRM,
        operator="memory-reviewer",
        reason="replacement procedure verified",
        created_at=NOW + timedelta(minutes=1),
    )
    store.commit_administrative_review(
        request,
        authority=AdministrativeMutationCAS(
            deployment_namespace=memory_environment.namespace,
            session_id=memory_environment.session_id,
            expected_stream_revision=5,
        ),
    )
    from agent_core.domain.governed_memories import GovernedMemoryManagementContext

    first_authority = store.get_authority(
        first.memory_id,
        management=GovernedMemoryManagementContext(
            operation_id=f"inspect:{first.memory_id}",
            operator="memory-test",
            reason="verify definition-scoped supersede",
        ),
    )
    second_authority = store.get_authority(
        second.memory_id,
        management=GovernedMemoryManagementContext(
            operation_id=f"inspect:{second.memory_id}",
            operator="memory-test",
            reason="verify definition-scoped supersede",
        ),
    )
    assert isinstance(first_authority, GovernedMemoryEntry)
    assert isinstance(second_authority, GovernedMemoryEntry)
    assert first_authority.record.status is MemoryStatus.SUPERSEDED
    assert first_authority.record.superseded_by == second.memory_id
    assert first_authority.record.definition_id == DEFINITION_ID
    assert first_authority.record.authority_issuer == ISSUER
    assert second_authority.record.status is MemoryStatus.CONFIRMED
    assert second_authority.record.definition_id == DEFINITION_ID
