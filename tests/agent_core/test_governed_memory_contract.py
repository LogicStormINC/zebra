from datetime import UTC, datetime, timedelta
from typing import get_type_hints
from uuid import UUID

import pytest
from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionPlanner,
    MemoryCandidatePromotionPlanner,
    MemoryReviewAction,
    MemoryReviewCommand,
    MemoryReviewService,
)
from agent_core.domain import (
    AdministrativeMemoryReviewRequest,
    GovernedMemoryCreate,
    GovernedMemoryEntry,
    GovernedMemoryLifecycleMutation,
    GovernedMemoryOperationKind,
    GovernedMemoryOperationReceipt,
    GovernedMemoryReviewAction,
    GovernedMemoryRevision,
    GovernedMemoryTombstone,
    WorkerMemoryMutationPlan,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, new_event_id, new_session_id
from agent_core.domain.leases import LeaseFence
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports import (
    AdministrativeMutationCAS,
    GovernedMemoryScanCursor,
    GovernedMemoryScanQuery,
    GovernedMemoryStorePort,
    WorkerMutationAuthority,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64


def test_authoritative_entry_rejects_deleted_record() -> None:
    with pytest.raises(ValueError, match="tombstone"):
        GovernedMemoryEntry(
            deployment_namespace="cloud-a",
            record=_candidate().model_copy(update={"status": MemoryStatus.DELETED}),
            revision=2,
            creation_key="session:event:candidate",
            content_digest=DIGEST,
        )


def test_tombstone_is_content_free_and_scope_checked() -> None:
    tombstone = GovernedMemoryTombstone(
        deployment_namespace="cloud-a",
        memory_id=_memory_id(1),
        revision=3,
        memory_type=MemoryType.PROCEDURE,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        provenance_digest=DIGEST,
        created_at=NOW,
        updated_at=NOW,
    )

    assert tombstone.status is MemoryStatus.DELETED
    assert "text" not in type(tombstone).model_fields
    with pytest.raises(ValueError, match="Extra inputs"):
        GovernedMemoryTombstone.model_validate({**tombstone.model_dump(), "text": "leak"})


def test_creation_requires_candidate_and_canonical_idempotency_evidence() -> None:
    creation = GovernedMemoryCreate.from_candidate(_candidate())

    assert creation.record.status is MemoryStatus.CANDIDATE
    with pytest.raises(ValueError, match="candidate status"):
        GovernedMemoryCreate(
            record=_candidate().model_copy(update={"status": MemoryStatus.CONFIRMED}),
            creation_key=canonical_governed_memory_creation_key(_candidate()),
            content_digest=canonical_governed_memory_content_hash(_candidate()),
        )


def test_creation_and_entry_reject_noncanonical_evidence() -> None:
    record = _candidate()
    creation = GovernedMemoryCreate.from_candidate(record)
    with pytest.raises(ValueError, match="content_digest"):
        GovernedMemoryCreate(
            record=record,
            creation_key=creation.creation_key,
            content_digest=DIGEST,
        )
    with pytest.raises(ValueError, match="creation_key"):
        GovernedMemoryEntry(
            deployment_namespace="cloud-a",
            record=record,
            revision=1,
            creation_key=DIGEST,
            content_digest=creation.content_digest,
        )


def test_canonical_content_and_creation_hashes_are_semantic_and_id_stable() -> None:
    record = _candidate()
    regenerated_id = record.model_copy(update={"memory_id": _memory_id(8)})
    regenerated_time = record.model_copy(
        update={"created_at": NOW + timedelta(minutes=1), "updated_at": NOW + timedelta(minutes=1)}
    )
    changed = record.model_copy(update={"text": "Run make test."})

    assert canonical_governed_memory_creation_key(record) == (
        canonical_governed_memory_creation_key(regenerated_id)
    )
    assert canonical_governed_memory_content_hash(record) == (
        canonical_governed_memory_content_hash(regenerated_time)
    )
    assert canonical_governed_memory_creation_key(record) == (
        canonical_governed_memory_creation_key(regenerated_time)
    )
    assert canonical_governed_memory_content_hash(record) != (
        canonical_governed_memory_content_hash(changed)
    )


def test_lifecycle_mutation_requires_revision_and_allowed_transition() -> None:
    mutation = GovernedMemoryLifecycleMutation(
        memory_id=_memory_id(1),
        expected_revision=1,
        previous_status=MemoryStatus.CONFIRMED,
        status=MemoryStatus.SUPERSEDED,
        superseded_by=_memory_id(2),
        updated_at=NOW,
    )

    assert mutation.expected_revision == 1
    with pytest.raises(ValueError, match="invalid Memory transition"):
        GovernedMemoryLifecycleMutation(
            memory_id=_memory_id(1),
            expected_revision=1,
            previous_status=MemoryStatus.DELETED,
            status=MemoryStatus.CONFIRMED,
            updated_at=NOW,
        )


def test_worker_and_administrative_authority_are_separate_port_inputs() -> None:
    worker_method = get_type_hints(GovernedMemoryStorePort.commit_worker_candidates)
    admin_method = get_type_hints(GovernedMemoryStorePort.commit_administrative_review)

    assert worker_method["authority"] is WorkerMutationAuthority
    assert admin_method["authority"] is AdministrativeMutationCAS


def test_administrative_review_requires_explicit_revision_and_audit() -> None:
    session = _session()
    request = AdministrativeMemoryReviewRequest.create(
        deployment_namespace="cloud-a",
        operation_id="review:1",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        memory_id=_memory_id(1),
        expected_revision=2,
        action=GovernedMemoryReviewAction.CONFIRM,
        operator="alice",
        reason="verified evidence",
        created_at=NOW,
    )

    assert request.expected_revision == 2
    with pytest.raises(ValueError):
        AdministrativeMemoryReviewRequest.model_validate(
            {
                key: value
                for key, value in request.model_dump().items()
                if key != "expected_revision"
            }
        )


def test_candidate_and_review_planners_need_no_store() -> None:
    session = _session()
    source = _source_event(session)
    candidate_plan = MemoryCandidateExtractionPlanner().plan(
        session=session,
        events=[source],
        next_sequence=5,
        command=MemoryCandidateExtractionCommand(repo_id="zebra-agent", extracted_at=NOW),
    )
    candidate = candidate_plan.records[0]
    review = MemoryReviewService().plan(
        session=session,
        record=candidate,
        next_sequence=5,
        command=MemoryReviewCommand(
            action=MemoryReviewAction.CONFIRM,
            operator="alice",
            reason="verified",
            created_at=NOW,
        ),
    )
    promotion = MemoryCandidatePromotionPlanner().plan(
        session=session,
        source_events=[source],
        candidates=(candidate,),
        promoted_at=NOW,
    )

    assert review.record.status is MemoryStatus.CONFIRMED
    assert promotion.records[0].status is MemoryStatus.CONFIRMED


def test_promotion_plan_observes_earlier_planned_confirmation() -> None:
    session = _session()
    source = _source_event(session)
    first = (
        MemoryCandidateExtractionPlanner()
        .plan(
            session=session,
            events=[source],
            next_sequence=5,
            command=MemoryCandidateExtractionCommand(repo_id="zebra-agent", extracted_at=NOW),
        )
        .records[0]
    )
    duplicate = first.model_copy(update={"memory_id": _memory_id(9)})

    plan = MemoryCandidatePromotionPlanner().plan(
        session=session,
        source_events=[source],
        candidates=(first, duplicate),
        promoted_at=NOW,
    )

    assert [record.status for record in plan.records] == [
        MemoryStatus.CONFIRMED,
        MemoryStatus.EXPIRED,
    ]


def test_planner_outputs_convert_to_canonical_worker_mutation_plan() -> None:
    session = _session()
    source = _source_event(session)
    extraction = MemoryCandidateExtractionPlanner().plan(
        session=session,
        events=[source],
        next_sequence=5,
        command=MemoryCandidateExtractionCommand(repo_id="zebra-agent", extracted_at=NOW),
    )
    candidate = extraction.records[0]
    promotion = MemoryCandidatePromotionPlanner().plan(
        session=session,
        source_events=[source],
        candidates=(candidate,),
        promoted_at=NOW,
    )
    creations, extraction_mutations = extraction.governed_mutations(expected_revisions={})
    promotion_mutations = promotion.governed_mutations(expected_revisions={candidate.memory_id: 1})
    events = extraction.events + promotion.events

    plan = WorkerMemoryMutationPlan.create(
        deployment_namespace="cloud-a",
        operation_id="worker:session:4",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        creations=creations,
        lifecycle_mutations=extraction_mutations + promotion_mutations,
        events=events,
    )
    reordered_event = events[0].model_copy(
        update={"payload": dict(reversed(tuple(events[0].payload.items())))}
    )
    reordered = WorkerMemoryMutationPlan.create(
        deployment_namespace="cloud-a",
        operation_id="worker:session:4",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        creations=creations,
        lifecycle_mutations=extraction_mutations + promotion_mutations,
        events=(reordered_event,) + events[1:],
    )
    regenerated_id = _memory_id(8)
    regenerated_creation = GovernedMemoryCreate.from_candidate(
        creations[0].record.model_copy(
            update={
                "memory_id": regenerated_id,
                "created_at": NOW + timedelta(minutes=3),
                "updated_at": NOW + timedelta(minutes=3),
            }
        )
    )
    regenerated_mutations = tuple(
        mutation.model_copy(
            update={
                "memory_id": (
                    regenerated_id
                    if mutation.memory_id == candidate.memory_id
                    else mutation.memory_id
                ),
                "superseded_by": (
                    regenerated_id
                    if mutation.superseded_by == candidate.memory_id
                    else mutation.superseded_by
                ),
                "updated_at": mutation.updated_at + timedelta(minutes=3),
            }
        )
        for mutation in extraction_mutations + promotion_mutations
    )
    regenerated_events = tuple(
        event.model_copy(
            update={
                "event_id": new_event_id(),
                "sequence": event.sequence + 20,
                "created_at": event.created_at + timedelta(minutes=3),
                "payload": {
                    key: (str(regenerated_id) if value == str(candidate.memory_id) else value)
                    for key, value in event.payload.items()
                },
            }
        )
        for event in events
    )
    regenerated = WorkerMemoryMutationPlan.create(
        deployment_namespace="cloud-a",
        operation_id="worker:session:4",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        creations=(regenerated_creation,),
        lifecycle_mutations=regenerated_mutations,
        events=regenerated_events,
    )
    changed_creation = GovernedMemoryCreate.from_candidate(
        candidate.model_copy(update={"text": "Run make test."})
    )
    changed = WorkerMemoryMutationPlan.create(
        deployment_namespace="cloud-a",
        operation_id="worker:session:4",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        creations=(changed_creation,),
        lifecycle_mutations=extraction_mutations + promotion_mutations,
        events=events,
    )

    assert plan.request_digest == reordered.request_digest
    assert plan.request_digest == regenerated.request_digest
    assert plan.request_digest != changed.request_digest
    assert plan.creations[0].creation_key == canonical_governed_memory_creation_key(candidate)
    assert plan.lifecycle_mutations[0].expected_revision == 1


def test_worker_plan_validation_binds_cas_but_not_lease_fence() -> None:
    session = _session()
    creation = GovernedMemoryCreate.from_candidate(
        _candidate().model_copy(update={"source_session_id": session.session_id})
    )
    authority = _worker_authority(session)
    event = _source_event(session)
    plan = WorkerMemoryMutationPlan.create(
        deployment_namespace="cloud-a",
        operation_id="worker:memory",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        creations=(creation,),
        events=(event,),
    )

    assert plan.validate_for("cloud-a", authority) is plan
    assert (
        plan.validate_for(
            "cloud-a",
            authority.model_copy(
                update={
                    "lease_fence": authority.lease_fence.model_copy(update={"fencing_token": 9})
                }
            ),
        )
        is plan
    )
    with pytest.raises(ValueError, match="authority CAS"):
        plan.validate_for(
            "cloud-a",
            authority.model_copy(update={"expected_stream_revision": 5}),
        )
    with pytest.raises(ValueError, match="namespace"):
        plan.validate_for("cloud-b", authority)
    with pytest.raises(ValueError, match="digest mismatch"):
        plan.model_copy(update={"request_digest": DIGEST}).validate_for("cloud-a", authority)
    tampered_creation = creation.model_copy(
        update={"record": creation.record.model_copy(update={"text": "tampered"})}
    )
    with pytest.raises(ValueError, match="does not match"):
        plan.model_copy(update={"creations": (tampered_creation,)}).validate_for(
            "cloud-a", authority
        )


def test_worker_noop_cannot_create_an_operation_receipt_request() -> None:
    session = _session()
    with pytest.raises(ValueError, match="requires mutations and Events"):
        WorkerMemoryMutationPlan.create(
            deployment_namespace="cloud-a",
            operation_id="worker:noop",
            session_id=session.session_id,
            expected_stream_revision=session.current_sequence,
        )


def test_administrative_review_validation_binds_cas_and_digest() -> None:
    session = _session()
    authority = AdministrativeMutationCAS(
        deployment_namespace="cloud-a",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
    )
    request = AdministrativeMemoryReviewRequest.create(
        deployment_namespace="cloud-a",
        operation_id="review:1",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        memory_id=_memory_id(1),
        expected_revision=1,
        action=GovernedMemoryReviewAction.CONFIRM,
        operator="alice",
        reason="verified",
        created_at=NOW,
    )

    assert request.validate_for("cloud-a", authority) is request
    regenerated_time = AdministrativeMemoryReviewRequest.create(
        deployment_namespace="cloud-a",
        operation_id="review:1",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        memory_id=_memory_id(1),
        expected_revision=1,
        action=GovernedMemoryReviewAction.CONFIRM,
        operator="alice",
        reason="verified",
        created_at=NOW + timedelta(minutes=5),
    )
    changed_reason = AdministrativeMemoryReviewRequest.create(
        deployment_namespace="cloud-a",
        operation_id="review:1",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        memory_id=_memory_id(1),
        expected_revision=1,
        action=GovernedMemoryReviewAction.CONFIRM,
        operator="alice",
        reason="different semantic review",
        created_at=NOW,
    )
    assert request.request_digest == regenerated_time.request_digest
    assert request.request_digest != changed_reason.request_digest
    with pytest.raises(ValueError, match="authority CAS"):
        request.validate_for(
            "cloud-a",
            authority.model_copy(update={"expected_stream_revision": 5}),
        )
    with pytest.raises(ValueError, match="namespace"):
        request.validate_for("cloud-b", authority)
    with pytest.raises(ValueError, match="digest mismatch"):
        request.model_copy(update={"reason": "tampered"}).validate_for("cloud-a", authority)


def test_scan_cursor_is_opaque_and_snapshot_bound() -> None:
    cursor = GovernedMemoryScanCursor(
        snapshot_token="snapshot:abc",
        position_token="position:200",
    )

    assert cursor.snapshot_token == "snapshot:abc"
    assert set(type(cursor).model_fields) == {"snapshot_token", "position_token"}
    with pytest.raises(ValueError, match="non-blank"):
        GovernedMemoryScanCursor(snapshot_token=" ", position_token="position:200")


@pytest.mark.parametrize(
    "scope",
    [
        MemoryQuery(repo_id="repo", user_id="user", visibility=MemoryVisibility.REPO),
        MemoryQuery(user_id="user", tenant_id="tenant", visibility=MemoryVisibility.USER),
        MemoryQuery(tenant_id="tenant", repo_id="repo", visibility=MemoryVisibility.TENANT),
        MemoryQuery(repo_id="repo"),
        MemoryQuery(repo_id="repo", text_query="needle", visibility=MemoryVisibility.REPO),
        MemoryQuery(
            repo_id="repo",
            source_session_id=new_session_id(),
            visibility=MemoryVisibility.REPO,
        ),
    ],
)
def test_scan_query_rejects_ambiguous_or_non_snapshot_filters(scope: MemoryQuery) -> None:
    with pytest.raises(ValueError):
        GovernedMemoryScanQuery(scope=scope)


def test_scan_query_accepts_one_exact_visibility_scope() -> None:
    query = GovernedMemoryScanQuery(
        scope=MemoryQuery(repo_id="repo", visibility=MemoryVisibility.REPO)
    )

    assert query.scope.repo_id == "repo"


def test_operation_receipt_freezes_content_free_canonical_result() -> None:
    event_ids = (new_event_id(), new_event_id())
    receipt = GovernedMemoryOperationReceipt.create(
        operation_id="worker:memory",
        operation_kind=GovernedMemoryOperationKind.WORKER_CANDIDATES,
        request_digest=DIGEST,
        memories=(
            GovernedMemoryRevision(
                memory_id=_memory_id(1), revision=2, status=MemoryStatus.CONFIRMED
            ),
        ),
        event_ids=event_ids,
        event_sequences=(5, 6),
        anchor_event_start=5,
        anchor_event_end=6,
        session_revision=6,
        projection_revision=6,
        committed_at=NOW,
    )
    replay_time = receipt.model_copy(update={"committed_at": NOW + timedelta(minutes=5)})

    assert receipt.result_schema == "governed-memory-operation-result/1"
    assert receipt.validate_canonical() is receipt
    assert replay_time.validate_canonical() is replay_time
    assert "text" not in receipt.model_dump_json()
    with pytest.raises(ValueError, match="result digest mismatch"):
        receipt.model_copy(
            update={"memories": (receipt.memories[0].model_copy(update={"revision": 3}),)}
        ).validate_canonical()
    with pytest.raises(ValueError, match="result schema mismatch"):
        receipt.model_copy(update={"result_schema": "tampered"}).validate_canonical()


@pytest.mark.parametrize(
    ("event_sequences", "anchor_end", "session_revision", "projection_revision"),
    [
        ((5, 7), 7, 7, 7),
        ((5, 6), 7, 7, 7),
        ((5, 6), 6, 7, 7),
        ((5, 6), 6, 6, 5),
    ],
)
def test_operation_receipt_rejects_invalid_anchor_or_revisions(
    event_sequences: tuple[int, ...],
    anchor_end: int,
    session_revision: int,
    projection_revision: int,
) -> None:
    with pytest.raises(ValueError):
        GovernedMemoryOperationReceipt.create(
            operation_id="worker:memory",
            operation_kind=GovernedMemoryOperationKind.WORKER_CANDIDATES,
            request_digest=DIGEST,
            memories=(),
            event_ids=(new_event_id(), new_event_id()),
            event_sequences=event_sequences,
            anchor_event_start=5,
            anchor_event_end=anchor_end,
            session_revision=session_revision,
            projection_revision=projection_revision,
            committed_at=NOW,
        )


def _memory_id(value: int) -> MemoryId:
    return MemoryId(UUID(int=value))


def _candidate() -> MemoryRecord:
    return MemoryRecord(
        memory_id=_memory_id(1),
        memory_type=MemoryType.PROCEDURE,
        text="Run make check.",
        confidence=0.9,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        source_session_id=new_session_id(),
        source_event_start=4,
        source_event_end=4,
        created_at=NOW,
        updated_at=NOW,
    )


def _session() -> Session:
    return Session(
        session_id=new_session_id(),
        title="memory contract",
        status=SessionStatus.COMPLETED,
        current_sequence=4,
        created_at=NOW,
        updated_at=NOW,
    )


def _worker_authority(session: Session) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace="cloud-a",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        lease_fence=LeaseFence(
            control_plane_epoch=UUID(int=99),
            fencing_token=1,
            owner_instance_id="worker-a",
        ),
    )


def _source_event(session: Session) -> SessionEvent:
    return SessionEvent.create(
        session_id=session.session_id,
        sequence=4,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "tests.run",
            "status": "executed",
            "output": "",
            "metadata": {
                "preset": "smoke",
                "command": ["make", "check"],
                "cwd": ".",
            },
        },
        created_at=NOW,
    )
