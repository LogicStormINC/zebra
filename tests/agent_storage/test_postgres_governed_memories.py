from __future__ import annotations

import os
from collections.abc import Generator
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryLifecycleMutation,
    GovernedMemoryTombstone,
)
from agent_core.domain.governed_memory_operations import WorkerMemoryMutationPlan
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.memory_delivery import MemoryDeliveryScope
from agent_storage import (
    PostgresEventStore,
    PostgresGovernedMemoryStore,
    apply_postgres_migrations,
)
from agent_storage.postgres.governed_memory_rows import provenance_digest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.agent_storage.governed_memory_test_support import (
    CURSOR_SIGNING_KEY,
    NOW,
)
from tests.agent_storage.governed_memory_test_support import (
    MemoryEnvironment as _MemoryEnvironment,
)
from tests.agent_storage.governed_memory_test_support import (
    aggregate_state as _aggregate_state,
)
from tests.agent_storage.governed_memory_test_support import (
    authority as _authority,
)
from tests.agent_storage.governed_memory_test_support import (
    candidate as _candidate,
)
from tests.agent_storage.governed_memory_test_support import (
    management as _management,
)
from tests.agent_storage.governed_memory_test_support import (
    plan as _plan,
)
from tests.agent_storage.governed_memory_test_support import (
    prepare_environment as _prepare_environment,
)
from tests.agent_storage.governed_memory_test_support import (
    review_event as _review_event,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"governed_memory_{uuid4().hex}"
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


def test_governed_memory_provenance_digest_is_stable_and_content_free() -> None:
    record = MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000001")),
        memory_type=MemoryType.PROCEDURE,
        text="Run make test.",
        confidence=0.9,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        source_session_id=SessionId(UUID("00000000-0000-0000-0000-000000000002")),
        source_event_start=3,
        source_event_end=5,
        source_commit_sha="abc123",
        created_at=NOW,
        updated_at=NOW,
    )

    assert provenance_digest(record) == (
        "c8cc634b6e9d9d57565cc236def131d41577709f633c77f1e04048ee7998d1d2"
    )
    assert provenance_digest(record.model_copy(update={"text": "Never persisted in digest"})) == (
        provenance_digest(record)
    )


def test_regenerated_creation_is_promoted_under_canonical_memory_id(
    memory_environment: _MemoryEnvironment,
) -> None:
    original = _candidate(memory_environment, text="Use the canonical Memory ID.")
    first_plan = _plan(
        memory_environment,
        operation_id="memory:create-canonical",
        expected_revision=1,
        records=(original,),
    )
    memory_environment.store.commit_worker_candidates(
        first_plan,
        authority=_authority(memory_environment, 1),
    )
    regenerated = original.model_copy(
        update={
            "memory_id": MemoryId(uuid4()),
            "created_at": NOW + timedelta(minutes=1),
            "updated_at": NOW + timedelta(minutes=1),
        }
    )
    promotion = _plan(
        memory_environment,
        operation_id="memory:promote-regenerated",
        expected_revision=2,
        records=(regenerated,),
        confirmed=(regenerated.memory_id,),
    )

    committed = memory_environment.store.commit_worker_candidates(
        promotion,
        authority=_authority(memory_environment, 2),
    )

    assert committed.receipt.memories == (
        committed.receipt.memories[0].model_copy(
            update={
                "memory_id": original.memory_id,
                "revision": 2,
                "status": MemoryStatus.CONFIRMED,
            }
        ),
    )
    assert memory_environment.store.get(regenerated.memory_id) is None
    assert memory_environment.store.get(original.memory_id).status is MemoryStatus.CONFIRMED  # type: ignore[union-attr]
    with psycopg.connect(memory_environment.dsn) as connection:
        assert connection.execute(
            """SELECT count(*) FROM governed_memory_records
            WHERE deployment_namespace = %s""",
            (memory_environment.namespace,),
        ).fetchone() == (1,)
    events = PostgresEventStore(
        memory_environment.dsn,
        deployment_namespace=memory_environment.namespace,
    ).list_for_session(memory_environment.session_id)
    assert [event.payload["memory_id"] for event in events[-2:]] == [
        str(original.memory_id),
        str(original.memory_id),
    ]


def test_delivery_scope_enqueues_confirmed_authority_once_on_replay(
    memory_environment: _MemoryEnvironment,
) -> None:
    delivery_scope = MemoryDeliveryScope(
        deployment_namespace=memory_environment.namespace,
        scope_digest="9" * 64,
        generation=1,
        revision=0,
    )
    store = PostgresGovernedMemoryStore(
        memory_environment.dsn,
        deployment_namespace=memory_environment.namespace,
        cursor_signing_key=CURSOR_SIGNING_KEY,
        delivery_scope=delivery_scope,
    )
    record = _candidate(memory_environment, text="atomically delivered fact")
    plan = _plan(
        memory_environment,
        operation_id="memory:delivery-atomic",
        expected_revision=1,
        records=(record,),
        confirmed=(record.memory_id,),
    )

    first = store.commit_worker_candidates(plan, authority=_authority(memory_environment, 1))
    replay = store.commit_worker_candidates(plan, authority=_authority(memory_environment, 1))

    assert not first.replayed
    assert replay.replayed
    with psycopg.connect(memory_environment.dsn) as connection:
        row = connection.execute(
            """
            SELECT count(*), min(state), min(memory_revision)
            FROM memory_delivery_operations
            WHERE deployment_namespace = %s AND memory_id = %s
            """,
            (memory_environment.namespace, record.memory_id),
        ).fetchone()
    assert row == (1, "pending", 2)


def test_worker_receipt_lookup_is_read_only_and_bound_to_its_session(
    memory_environment: _MemoryEnvironment,
) -> None:
    record = _candidate(memory_environment, text="read the committed Worker receipt")
    plan = _plan(
        memory_environment,
        operation_id="memory:receipt-lookup",
        expected_revision=1,
        records=(record,),
        confirmed=(record.memory_id,),
    )

    committed = memory_environment.store.commit_worker_candidates(
        plan,
        authority=_authority(memory_environment, 1),
    )
    receipt = memory_environment.store.get_worker_commit_receipt(
        plan.operation_id,
        session_id=memory_environment.session_id,
    )

    assert receipt is not None
    assert receipt.replayed
    assert receipt.receipt == committed.receipt
    with pytest.raises(GovernedMemoryConflictError, match="session"):
        memory_environment.store.get_worker_commit_receipt(
            plan.operation_id,
            session_id=SessionId(uuid4()),
        )


def test_delete_retains_content_free_tombstone_and_hides_compatibility_reads(
    memory_environment: _MemoryEnvironment,
) -> None:
    store = PostgresGovernedMemoryStore(
        memory_environment.dsn,
        deployment_namespace=memory_environment.namespace,
        cursor_signing_key=CURSOR_SIGNING_KEY,
        delivery_scope=MemoryDeliveryScope(
            deployment_namespace=memory_environment.namespace,
            scope_digest="8" * 64,
            generation=1,
            revision=0,
        ),
    )
    record = _candidate(memory_environment, text="Delete this governed fact.")
    created = _plan(
        memory_environment,
        operation_id="memory:create-before-delete",
        expected_revision=1,
        records=(record,),
        confirmed=(record.memory_id,),
    )
    store.commit_worker_candidates(
        created,
        authority=_authority(memory_environment, 1),
    )
    deletion = GovernedMemoryLifecycleMutation(
        memory_id=record.memory_id,
        expected_revision=2,
        previous_status=MemoryStatus.CONFIRMED,
        status=MemoryStatus.DELETED,
        updated_at=NOW + timedelta(minutes=2),
    )
    plan = WorkerMemoryMutationPlan.create(
        deployment_namespace=memory_environment.namespace,
        operation_id="memory:delete",
        session_id=memory_environment.session_id,
        expected_stream_revision=3,
        lifecycle_mutations=(deletion,),
        events=(
            _review_event(
                record,
                previous_status=MemoryStatus.CONFIRMED,
                status=MemoryStatus.DELETED,
                sequence=4,
                created_at=deletion.updated_at,
            ),
        ),
    )

    committed = store.commit_worker_candidates(
        plan,
        authority=_authority(memory_environment, 3),
    )

    assert committed.receipt.memories[0].status is MemoryStatus.DELETED
    assert committed.receipt.memories[0].revision == 3
    assert store.get(record.memory_id) is None
    assert (
        store.list(
            MemoryQuery(
                repo_id="zebra-agent",
                visibility=MemoryVisibility.REPO,
                statuses=(),
            )
        )
        == []
    )
    authority = store.get_authority(
        record.memory_id,
        management=_management("memory:inspect-tombstone"),
    )
    assert isinstance(authority, GovernedMemoryTombstone)
    assert "text" not in type(authority).model_fields
    with psycopg.connect(memory_environment.dsn) as connection:
        assert connection.execute(
            """SELECT status, text, revision FROM governed_memory_records
            WHERE deployment_namespace = %s AND memory_id = %s""",
            (memory_environment.namespace, record.memory_id),
        ).fetchone() == ("deleted", None, 3)
        assert connection.execute(
            """
            SELECT operation, memory_revision, state
            FROM memory_delivery_operations
            WHERE deployment_namespace = %s AND memory_id = %s
            ORDER BY memory_revision
            """,
            (memory_environment.namespace, record.memory_id),
        ).fetchall() == [("publish", 2, "pending"), ("delete", 3, "pending")]


@pytest.mark.parametrize("fault", ["fence", "stream"])
def test_stale_worker_authority_writes_nothing(
    memory_environment: _MemoryEnvironment,
    fault: str,
) -> None:
    expected = 1 if fault == "fence" else 0
    record = _candidate(memory_environment, text=f"Rejected stale {fault}.")
    plan = _plan(
        memory_environment,
        operation_id=f"memory:stale-{fault}",
        expected_revision=expected,
        records=(record,),
    )
    authority = _authority(memory_environment, expected)
    if fault == "fence":
        authority = authority.model_copy(
            update={
                "lease_fence": authority.lease_fence.model_copy(
                    update={"fencing_token": authority.lease_fence.fencing_token + 1}
                )
            }
        )
    before = _aggregate_state(memory_environment)

    with pytest.raises((LeaseLostError, GovernedMemoryConflictError)):
        memory_environment.store.commit_worker_candidates(plan, authority=authority)

    assert _aggregate_state(memory_environment) == before


def test_lost_response_replays_canonical_receipt_with_regenerated_ids(
    memory_environment: _MemoryEnvironment,
) -> None:
    record = _candidate(memory_environment, text="Replay the frozen result.")
    plan = _plan(
        memory_environment,
        operation_id="memory:lost-response",
        expected_revision=1,
        records=(record,),
    )

    def lose_response() -> None:
        memory_environment.store.commit_worker_candidates(
            plan,
            authority=_authority(memory_environment, 1),
        )
        raise ConnectionError("response lost after commit")

    with pytest.raises(ConnectionError, match="response lost"):
        lose_response()
    stored_state = _aggregate_state(memory_environment)
    regenerated = record.model_copy(
        update={
            "memory_id": MemoryId(uuid4()),
            "created_at": NOW + timedelta(minutes=5),
            "updated_at": NOW + timedelta(minutes=5),
        }
    )
    retry = _plan(
        memory_environment,
        operation_id=plan.operation_id,
        expected_revision=1,
        records=(regenerated,),
    )

    replayed = memory_environment.store.commit_worker_candidates(
        retry,
        authority=_authority(memory_environment, 1),
    )

    assert replayed.replayed
    assert replayed.receipt.operation_id == plan.operation_id
    assert replayed.receipt.memories[0].memory_id == record.memory_id
    assert _aggregate_state(memory_environment) == stored_state


@pytest.mark.parametrize("corruption", ["result_digest", "event_anchor"])
def test_operation_replay_fails_closed_on_row_evidence_corruption(
    memory_environment: _MemoryEnvironment,
    corruption: str,
) -> None:
    record = _candidate(memory_environment, text=f"Corrupt {corruption}.")
    plan = _plan(
        memory_environment,
        operation_id=f"memory:corrupt-{corruption}",
        expected_revision=1,
        records=(record,),
    )
    memory_environment.store.commit_worker_candidates(
        plan,
        authority=_authority(memory_environment, 1),
    )
    with psycopg.connect(memory_environment.dsn) as connection:
        if corruption == "result_digest":
            connection.execute(
                """UPDATE governed_memory_operations SET result_digest = %s
                WHERE deployment_namespace = %s AND operation_id = %s""",
                ("f" * 64, memory_environment.namespace, plan.operation_id),
            )
        else:
            first = connection.execute(
                """SELECT event_id FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s AND sequence = 0""",
                (memory_environment.namespace, memory_environment.session_id),
            ).fetchone()
            assert first is not None
            connection.execute(
                """UPDATE governed_memory_operations
                SET anchor_event_start = 0, anchor_event_end = 0,
                    anchor_start_event_id = %s, anchor_end_event_id = %s
                WHERE deployment_namespace = %s AND operation_id = %s""",
                (
                    first[0],
                    first[0],
                    memory_environment.namespace,
                    plan.operation_id,
                ),
            )

    with pytest.raises(GovernedMemoryConflictError):
        memory_environment.store.commit_worker_candidates(
            plan,
            authority=_authority(memory_environment, 1),
        )


def test_namespace_and_query_contracts_use_postgres_authority(
    memory_environment: _MemoryEnvironment,
) -> None:
    records = (
        _candidate(memory_environment, text="alpha zebra", offset=1),
        _candidate(
            memory_environment,
            text="beta zebra",
            memory_type=MemoryType.EPISODIC,
            offset=2,
        ),
        _candidate(memory_environment, text="unreviewed candidate", offset=3),
        _candidate(
            memory_environment,
            text="user memory",
            visibility=MemoryVisibility.USER,
            user_id="user-a",
            offset=4,
        ),
    )
    plan = _plan(
        memory_environment,
        operation_id="memory:query-fixtures",
        expected_revision=1,
        records=records,
        confirmed=tuple(record.memory_id for record in (*records[:2], *records[3:])),
    )
    memory_environment.store.commit_worker_candidates(
        plan,
        authority=_authority(memory_environment, 1),
    )
    final_stream_revision = 1 + len(plan.events)

    repo_all = memory_environment.store.list(
        MemoryQuery(
            repo_id="zebra-agent",
            visibility=MemoryVisibility.REPO,
            statuses=(),
        )
    )
    assert {record.memory_id for record in repo_all} == {record.memory_id for record in records[:3]}
    assert {
        record.memory_id
        for record in memory_environment.store.list(
            MemoryQuery(
                repo_id="zebra-agent",
                visibility=MemoryVisibility.REPO,
                text_query="zebra",
            )
        )
    } == {records[0].memory_id, records[1].memory_id}
    assert (
        memory_environment.store.list(
            MemoryQuery(
                user_id="user-a",
                visibility=MemoryVisibility.USER,
            )
        )[0].memory_id
        == records[3].memory_id
    )
    worker_entries = memory_environment.store.list_for_worker(
        MemoryQuery(
            repo_id="zebra-agent",
            visibility=MemoryVisibility.REPO,
        ),
        authority=_authority(memory_environment, final_stream_revision),
    )
    assert {entry.record.memory_id for entry in worker_entries} == {
        records[0].memory_id,
        records[1].memory_id,
    }
    with pytest.raises(GovernedMemoryConflictError, match="revision"):
        memory_environment.store.list_for_worker(
            MemoryQuery(
                repo_id="zebra-agent",
                visibility=MemoryVisibility.REPO,
            ),
            authority=_authority(memory_environment, final_stream_revision - 1),
        )

    other = _prepare_environment(memory_environment.dsn)
    other_record = _candidate(
        other,
        memory_id=records[0].memory_id,
        text="same ID in another namespace",
    )
    other.store.commit_worker_candidates(
        _plan(
            other,
            operation_id="memory:other-namespace",
            expected_revision=1,
            records=(other_record,),
        ),
        authority=_authority(other, 1),
    )
    assert memory_environment.store.get(records[0].memory_id).text == "alpha zebra"  # type: ignore[union-attr]
    assert other.store.get(records[0].memory_id).text == "same ID in another namespace"  # type: ignore[union-attr]
