"""Concurrent idempotency over real PostgreSQL (2026-08-20 audit P1s).

Two races the serial tests cannot see:
- N concurrent admissions sharing one idempotency key must produce ONE
  session and N identical replays (no UniqueViolation, no second Task);
- N concurrent delegations sharing one frozen key must produce ONE child
  and N-1 replay receipts of the winner (no DelegationReplayError).
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.identifiers import TaskId
from agent_core.domain.parent_continuation import ChildTerminalStatus
from agent_core.domain.subagent_delegation import SubagentDelegationRequest
from agent_core.domain.subagents import SubagentRole
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot,
    HostCapabilitySnapshot,
    TaskBindingSnapshot,
)
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from agent_storage.postgres.subagent_delegation import (
    PostgresSubagentDelegationStore,
)
from agent_storage.postgres.task_admission import (
    PostgresTaskAdmissionTransaction,
)
from psycopg import connect

CAPS = capability_set(["agent.execute", "evidence.read"])
WORKERS = 16


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"conc-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


def _binding(task_id: TaskId) -> TaskBindingSnapshot:
    ceiling = AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="a" * 64,
        capability_profile_ref="profile/parent@1",
        capabilities=CAPS,
        resolved_at=datetime.now(UTC),
    )
    host = HostCapabilitySnapshot(
        host_app_id="host-conc",
        authority_issuer="https://host-conc.example.com",
        namespace_id="tenant-conc",
        grant_digest="c" * 64,
        grant_expires_at=datetime.now(UTC) + timedelta(hours=1),
        connector_id="host-conc-main",
        connector_profile_revision=1,
        connector_profile_digest="d" * 64,
        manifest_digest="b" * 64,
        capabilities=CAPS,
        resource_binding_digest="e" * 64,
        bound_at=datetime.now(UTC),
    )
    return TaskBindingSnapshot(
        task_id=str(task_id),
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest="f" * 64,
        effective_capabilities=CAPS,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )


def _admission(idempotency: IdempotencyRecord | None):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="concurrent",
            user_input="concurrent idempotency probe",
            workspace_root="/tmp/concurrent-probe",
            policy_profile="read_only",
            network_profile="none",
        )
    )
    return TaskAdmissionRequest(
        events=tuple(bootstrap.events),
        session=bootstrap.session,
        workspace=rebuild_workspace(list(bootstrap.events)),
        binding=_binding(TaskId(bootstrap.session.session_id)),
        idempotency=idempotency,
    )


def test_concurrent_admissions_share_one_idempotent_session(
    postgres_dsn: str, namespace: str
) -> None:
    key = f"conc-adm-{uuid4()}"
    receipt = IdempotencyRecord(
        action="session.create",
        idempotency_key=key,
        request_hash="1" * 64,
        status_code=201,
        response_body={"session_id": str(uuid4())},
        created_at=datetime.now(UTC),
    )
    def admit(_: int):
        transaction = PostgresTaskAdmissionTransaction(
            postgres_dsn, deployment_namespace=namespace
        )
        return transaction.admit(_admission(receipt))

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        receipts = list(executor.map(admit, range(WORKERS)))

    created = [r for r in receipts if not r.idempotent_replay]
    replayed = [r for r in receipts if r.idempotent_replay]
    assert len(created) == 1, "exactly one admission may create the Task"
    assert len(replayed) == WORKERS - 1
    for r in replayed:
        assert r.replayed_record is not None
        assert r.replayed_record.request_hash == "1" * 64
        assert r.replayed_record.response_body == receipt.response_body
    with connect(postgres_dsn) as connection:
        rows = connection.execute(
            """
            SELECT count(*) FROM session_streams
            WHERE deployment_namespace = %s
            """,
            (namespace,),
        ).fetchone()
    assert rows[0] == 1, "no duplicate sessions may survive the race"


def test_concurrent_delegations_replay_the_winner(
    postgres_dsn: str, namespace: str
) -> None:
    parent = TaskId(uuid4())
    parent_binding = _binding(parent)
    request = SubagentDelegationRequest(
        parent_task_id=parent,
        parent_attempt_number=1,
        parent_tool_call_id="call-conc-1",
        delegation_index=0,
        role=SubagentRole.RESEARCHER,
        objective="concurrent delegation probe",
        requested_capabilities=CAPS,
        child_definition_snapshot_digest="0" * 64,
        child_capability_profile_ref="profile/researcher@1",
        expected_parent_binding_digest=parent_binding.binding_digest,
    )

    def delegate(_: int):
        store = PostgresSubagentDelegationStore(
            postgres_dsn, deployment_namespace=namespace
        )
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="Research: concurrent delegation probe",
                user_input="concurrent delegation probe",
                workspace_root="/tmp/concurrent-probe",
                policy_profile="read_only",
                network_profile="none",
            )
        )
        from agent_core.domain.subagent_delegation import derive_child_binding

        child_binding = derive_child_binding(
            parent_binding,
            request,
            child_task_id=TaskId(bootstrap.session.session_id),
            child_definition_ceiling=CAPS,
            zebra_child_policy_capabilities=CAPS,
        )
        return store.delegate(
            request,
            TaskAdmissionRequest(
                events=tuple(bootstrap.events),
                session=bootstrap.session,
                workspace=rebuild_workspace(list(bootstrap.events)),
                binding=child_binding,
            ),
        )

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        receipts = list(executor.map(delegate, range(WORKERS)))

    materialized = [r for r in receipts if r.status == "materialized"]
    replayed = [r for r in receipts if r.status == "replayed"]
    assert len(materialized) == 1, "exactly one delegation may materialize a child"
    assert len(replayed) == WORKERS - 1, "losers must replay the winner, not error"
    winner_child = materialized[0].child_task_id
    for r in replayed:
        assert r.child_task_id == winner_child
        assert r.child_binding_digest == materialized[0].child_binding_digest
    with connect(postgres_dsn) as connection:
        links = connection.execute(
            """
            SELECT count(*) FROM subagent_delegation_links
            WHERE deployment_namespace = %s AND parent_task_id = %s
            """,
            (namespace, str(parent)),
        ).fetchone()
        children = connection.execute(
            """
            SELECT count(*) FROM session_streams
            WHERE deployment_namespace = %s
            """,
            (namespace,),
        ).fetchone()
    assert links[0] == 1, "exactly one delegation link may survive"
    assert children[0] == 1, "loser children must roll back with their transactions"


def _wakeup_setup(postgres_dsn: str, namespace: str, *, children: int):
    """Admit a parent, delegate N children, freeze the epoch, no terminals."""

    from agent_core.domain.agent_capabilities import capability_set as caps
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.subagent_delegation import derive_child_binding
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.events import append_event_in_transaction

    admission = PostgresTaskAdmissionTransaction(
        postgres_dsn, deployment_namespace=namespace
    )
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="wakeup parent",
            user_input="delegate research",
            workspace_root="/tmp/wu-parent",
            policy_profile="read_only",
            network_profile="none",
        )
    )
    parent = TaskId(bootstrap.session.session_id)
    parent_binding = _binding(parent)
    admission.admit(
        TaskAdmissionRequest(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=parent_binding,
        )
    )
    store = PostgresSubagentDelegationStore(
        postgres_dsn, deployment_namespace=namespace
    )
    child_ids: list[TaskId] = []
    for index in range(children):
        child_bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title=f"wakeup child {index}",
                user_input=f"objective {index}",
                workspace_root="/tmp/wu-child",
                policy_profile="read_only",
                network_profile="none",
            )
        )
        child = TaskId(child_bootstrap.session.session_id)
        request = SubagentDelegationRequest(
            parent_task_id=parent,
            parent_attempt_number=1,
            parent_tool_call_id=f"call-wu-{index}",
            delegation_index=index,
            role=SubagentRole.RESEARCHER,
            objective=f"objective {index}",
            requested_capabilities=caps(["evidence.read"]),
            child_definition_snapshot_digest="2" * 64,
            child_capability_profile_ref="profile/researcher@1",
            expected_parent_binding_digest=parent_binding.binding_digest,
        )
        store.delegate(
            request,
            TaskAdmissionRequest(
                events=tuple(child_bootstrap.events),
                session=child_bootstrap.session,
                workspace=rebuild_workspace(list(child_bootstrap.events)),
                binding=derive_child_binding(
                    parent_binding,
                    request,
                    child_task_id=child,
                    child_definition_ceiling=caps(["evidence.read"]),
                    zebra_child_policy_capabilities=caps(["evidence.read"]),
                ),
            ),
        )
        child_ids.append(child)
    database = PostgresDatabase(postgres_dsn, deployment_namespace=namespace)
    with database.connect() as connection:
        current = connection.execute(
            """
            SELECT COALESCE(MAX(sequence), -1) AS current_sequence
            FROM session_events
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (namespace, str(parent)),
        ).fetchone()
        sequence = int(current["current_sequence"])
        for index, child in enumerate(child_ids):
            sequence += 1
            append_event_in_transaction(
                connection,
                namespace,
                SessionEvent.create(
                    session_id=bootstrap.session.session_id,
                    sequence=sequence,
                    event_type=EventType.SUBAGENT_DELEGATED,
                    actor=EventActor.HARNESS,
                    payload={
                        "attempt_number": 1,
                        "child_task_id": str(child),
                        "tool_name": "agent.research",
                        "tool_call_id": f"call-wu-{index}",
                        "arguments": {
                            "objective": f"objective {index}",
                            "delegation_reason": "concurrency probe",
                        },
                        "assistant_message": "delegating",
                        "conversation": [],
                        "model_calls_used": 1,
                        "tool_calls_executed": 1,
                    },
                    created_at=datetime.now(UTC),
                ),
            )
    return parent, child_ids


def _complete_child(postgres_dsn: str, namespace: str, child: TaskId) -> None:
    with connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE session_projections
            SET status = 'completed', updated_at = NOW()
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (namespace, str(child)),
        )


def _harness_resume_events(postgres_dsn: str, namespace: str, parent: TaskId):
    with connect(postgres_dsn) as connection:
        rows = connection.execute(
            """
            SELECT payload, actor FROM session_events
            WHERE deployment_namespace = %s AND session_id = %s
                AND event_type = 'session_command_accepted'
                AND actor = 'harness'
                AND payload ->> 'kind' = 'resume'
            """,
            (namespace, str(parent)),
        ).fetchall()
    return rows


def test_concurrent_same_child_yields_exactly_one_wakeup(
    postgres_dsn: str, namespace: str
) -> None:
    from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService

    parent, children = _wakeup_setup(postgres_dsn, namespace, children=1)
    _complete_child(postgres_dsn, namespace, children[0])
    wakeup = ChildCompletionWakeupService(
        postgres_dsn, deployment_namespace=namespace
    )

    def process(_: int):
        return wakeup.process_child_terminal(
            children[0], status=ChildTerminalStatus.COMPLETED
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(process, range(8)))

    resumes = [r for r in results if r is not None and r["decision"] == "resume"]
    waits = [r for r in results if r is not None and r["decision"] == "keep_waiting"]
    assert len(resumes) + len(waits) == 8
    assert resumes, "the settled epoch must resume at least once"
    events = _harness_resume_events(postgres_dsn, namespace, parent)
    assert len(events) == 1, (
        f"expected exactly one wakeup event, saw {len(events)}"
    )


def test_concurrent_distinct_children_join_into_one_wakeup(
    postgres_dsn: str, namespace: str
) -> None:
    from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService

    parent, children = _wakeup_setup(postgres_dsn, namespace, children=2)
    _complete_child(postgres_dsn, namespace, children[0])
    _complete_child(postgres_dsn, namespace, children[1])
    wakeup = ChildCompletionWakeupService(
        postgres_dsn, deployment_namespace=namespace
    )
    barrier = threading.Barrier(2, timeout=30)

    def process(child: TaskId):
        barrier.wait()
        return wakeup.process_child_terminal(
            child, status=ChildTerminalStatus.COMPLETED
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(process, children))

    assert any(
        r is not None and r["decision"] == "resume" for r in results
    ), "one of the concurrent terminals must settle the epoch"
    events = _harness_resume_events(postgres_dsn, namespace, parent)
    assert len(events) == 1, (
        f"expected exactly one joined wakeup event, saw {len(events)}"
    )
    delivered = events[0][0]["payload"]["child_results"]
    assert {result["child_task_id"] for result in delivered} == {
        str(child) for child in children
    }, "the single wakeup must carry BOTH children's results"


def test_cancelled_child_produces_verifiable_wakeup(
    postgres_dsn: str, namespace: str
) -> None:
    """A legally cancelled child must still settle its epoch: the wakeup
    carries the canonical fallback summary and the durable reader agrees."""

    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.events import append_event_in_transaction
    from agent_storage.postgres.subagent_delegation import (
        child_terminal_summary_in_transaction,
    )
    from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService

    parent, children = _wakeup_setup(postgres_dsn, namespace, children=1)
    child = children[0]
    database = PostgresDatabase(postgres_dsn, deployment_namespace=namespace)
    with database.connect() as connection:
        current = connection.execute(
            """
            SELECT COALESCE(MAX(sequence), -1) AS current_sequence
            FROM session_events
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (namespace, str(child)),
        ).fetchone()
        append_event_in_transaction(
            connection,
            namespace,
            SessionEvent.create(
                session_id=child,
                sequence=int(current["current_sequence"]) + 1,
                event_type=EventType.SESSION_CANCELLED,
                actor=EventActor.SYSTEM,
                payload={"reason": "user cancelled"},
                created_at=datetime.now(UTC),
            ),
        )
    with connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE session_projections
            SET status = 'cancelled', updated_at = NOW()
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (namespace, str(child)),
        )

    wakeup = ChildCompletionWakeupService(
        postgres_dsn, deployment_namespace=namespace
    )
    result = wakeup.process_child_terminal(
        child, status=ChildTerminalStatus.CANCELLED
    )
    assert result is not None
    assert result["decision"] == "resume", "all_terminal must settle on cancel"

    events = _harness_resume_events(postgres_dsn, namespace, parent)
    assert len(events) == 1
    delivered = events[0][0]["payload"]["child_results"]
    assert delivered[0]["status"] == "cancelled"
    with database.connect() as connection:
        trusted = child_terminal_summary_in_transaction(
            connection, namespace, child
        )
    assert delivered[0]["summary"] == trusted, (
        "the delivered summary must equal the durable canonical form the "
        "Worker verifier re-reads"
    )


def test_canonical_summary_never_has_edge_whitespace_and_fits_budget() -> None:
    """Truncation boundaries may land after a space — the canonical form
    keeps both ends whitespace-free so the recovery side's defensive
    strip can never rewrite it, and budgets the JSON-escaped bytes the
    command contract actually measures (CJK escapes to 6 bytes/char)."""

    from agent_storage.postgres.subagent_delegation import (
        _canonical_summary,
        _json_bytes,
    )

    cjk_heavy = ("摘要内容测试 " * 600) + "尾巴" * 900
    canonical = _canonical_summary(cjk_heavy)
    assert canonical == canonical.strip(), "no edge whitespace may survive"
    assert _json_bytes(canonical) <= 3 * 1024

    spacy = "ab " * 1400
    spacy_canonical = _canonical_summary(spacy)
    assert spacy_canonical == spacy_canonical.strip()
    assert _json_bytes(spacy_canonical) <= 3 * 1024
    # The un-truncated spacy text fits only after cutting; verify the cut
    # really happened so the boundary case is exercised.
    assert len(spacy_canonical) < len(spacy)


def test_sixteen_children_wakeup_fits_command_contract(
    postgres_dsn: str, namespace: str
) -> None:
    """16 children with long Chinese answers: the wakeup payload must
    pass the SessionCommand contract (≤64 KiB JSON-escaped) and every
    delivered summary must equal the canonical durable form."""

    from agent_core.contracts import SessionCommand
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import SessionId
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.events import append_event_in_transaction
    from agent_storage.postgres.subagent_delegation import (
        child_terminal_summary_in_transaction,
    )
    from zebra_agent_worker.child_wakeup import ChildCompletionWakeupService

    parent, children = _wakeup_setup(postgres_dsn, namespace, children=16)
    long_answer = "部署回滚手册要点" * 500  # ~4000 CJK chars → ~24 KiB JSON
    database = PostgresDatabase(postgres_dsn, deployment_namespace=namespace)
    for child in children:
        with database.connect() as connection:
            current = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) AS current_sequence
                FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (namespace, str(child)),
            ).fetchone()
            append_event_in_transaction(
                connection,
                namespace,
                SessionEvent.create(
                    session_id=child,
                    sequence=int(current["current_sequence"]) + 1,
                    event_type=EventType.SESSION_COMPLETED,
                    actor=EventActor.HARNESS,
                    payload={
                        "attempt_number": 1,
                        "summary": "model completed without tool calls",
                        "metadata": {"assistant_message": long_answer},
                    },
                    created_at=datetime.now(UTC),
                ),
            )
        with connect(postgres_dsn) as connection:
            connection.execute(
                """
                UPDATE session_projections
                SET status = 'completed', updated_at = NOW()
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (namespace, str(child)),
            )

    wakeup = ChildCompletionWakeupService(
        postgres_dsn, deployment_namespace=namespace
    )
    # Terminalize the children the way the poll loop would, one by one:
    # every intermediate step keeps waiting; the LAST settles the epoch.
    for child in children[:-1]:
        waiting = wakeup.process_child_terminal(
            child, status=ChildTerminalStatus.COMPLETED
        )
        assert waiting is not None
        assert waiting["decision"] == "keep_waiting"
    result = wakeup.process_child_terminal(
        children[-1], status=ChildTerminalStatus.COMPLETED
    )
    assert result is not None
    assert result["decision"] == "resume"

    events = _harness_resume_events(postgres_dsn, namespace, parent)
    assert len(events) == 1
    payload = events[0][0]
    delivered = payload["payload"]["child_results"]
    assert len(delivered) == 16
    # Exactly the contract the SessionCommandConsumer reconstructs.
    command = SessionCommand(
        command_id=UUID(payload["command_id"]),
        session_id=SessionId(UUID(payload["session_id"])),
        kind=payload["kind"],
        expected_revision=payload["expected_revision"],
        idempotency_key=payload["idempotency_key"],
        payload=payload["payload"],
    )
    assert command.kind.value == "resume"
    encoded = json.dumps(command.payload, sort_keys=True, separators=(",", ":"))
    assert len(encoded.encode()) <= 64 * 1024
    with database.connect() as connection:
        for item in delivered:
            trusted = child_terminal_summary_in_transaction(
                connection, namespace, TaskId(UUID(item["child_task_id"]))
            )
            assert item["summary"] == trusted, (
                "delivered summaries must equal the canonical durable form"
            )
