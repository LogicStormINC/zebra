from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.artifact_objects import ArtifactObjectExpectation
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadStateError,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactBeginPruneRequest,
    ArtifactEventBinding,
    ArtifactFinalizeRequest,
    ArtifactManagementContext,
    ArtifactMetadataQuery,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId, new_session_id
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports import AdministrativeMutationCAS, WorkerMutationAuthority
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    PostgresLeaseStore,
    S3ArtifactObjectStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.session import Session  # type: ignore[import-untyped]
from psycopg import sql
from psycopg.conninfo import make_conninfo
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"tool_output_artifact_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_tool_output_commits_postgres_event_and_versioned_object(dsn: str) -> None:
    context = _context(dsn)
    projected = context.coordinator.output_projector.project_text(
        "complete cloud tool output",
        artifact_name="command-run.txt",
    )
    event = context.coordinator.append_draft(
        _terminal_draft(projected.model_output, projected.metadata),
        cast(DurableHarnessEventRecorder, context.recorder),
    )
    artifact_id = _artifact_id(projected.metadata)
    metadata = context.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=context.namespace,
            artifact_id=artifact_id,
            session_id=context.session_id,
        )
    )

    assert event.sequence == 1
    assert metadata is not None
    assert metadata.lifecycle_status is CloudArtifactPayloadLifecycleStatus.FINALIZED
    assert metadata.event_binding is not None
    assert metadata.event_binding.event_id == event.event_id
    expectation = ArtifactObjectExpectation(
        deployment_namespace=context.namespace,
        artifact_id=artifact_id,
        sha256=metadata.reservation.sha256,
        size_bytes=metadata.reservation.size_bytes,
    )
    assert context.objects.read_verified(expectation) == b"complete cloud tool output"


def test_failed_tool_output_uses_the_same_managed_lifecycle(dsn: str) -> None:
    context = _context(dsn)
    projected = context.coordinator.output_projector.project_text(
        "failed tool evidence",
        artifact_name="failed-command.txt",
    )
    event = context.coordinator.append_draft(
        _terminal_draft(
            projected.model_output,
            projected.metadata,
            event_type=EventType.TOOL_EXECUTION_FAILED,
            status="failed",
        ),
        cast(DurableHarnessEventRecorder, context.recorder),
    )
    artifact_id = _artifact_id(projected.metadata)
    metadata = context.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=context.namespace,
            artifact_id=artifact_id,
            session_id=context.session_id,
        )
    )

    assert event.event_type is EventType.TOOL_EXECUTION_FAILED
    assert metadata is not None
    assert metadata.lifecycle_status is CloudArtifactPayloadLifecycleStatus.FINALIZED


def test_concurrent_retention_prune_has_one_audited_winner(dsn: str) -> None:
    context = _context(dsn)
    projected = context.coordinator.output_projector.project_text(
        "retained output",
        artifact_name="retention.txt",
    )
    context.coordinator.append_draft(
        _terminal_draft(projected.model_output, projected.metadata),
        cast(DurableHarnessEventRecorder, context.recorder),
    )
    artifact_id = _artifact_id(projected.metadata)
    authority = AdministrativeMutationCAS(
        deployment_namespace=context.namespace,
        session_id=context.session_id,
        expected_stream_revision=1,
    )

    def begin(index: int) -> object | None:
        try:
            return context.metadata.begin_retention_prune(
                ArtifactBeginPruneRequest(
                    artifact_id=artifact_id,
                    session_id=context.session_id,
                    expected_lifecycle_revision=2,
                    idempotency_key=f"retention-prune-{index}",
                    requested_at=datetime.now(UTC),
                ),
                authority=authority,
                audit=ArtifactManagementContext(
                    operation_id=uuid4(),
                    operator_id="retention-sweeper",
                    reason=f"concurrent retention sweep {index}",
                ),
            )
        except CloudArtifactPayloadStateError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(begin, range(2)))

    assert sum(result is not None for result in results) == 1
    current = context.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=context.namespace,
            artifact_id=artifact_id,
            session_id=context.session_id,
        )
    )
    assert current is not None
    assert current.lifecycle_status is CloudArtifactPayloadLifecycleStatus.PRUNING
    with psycopg.connect(dsn) as connection:
        audit_count = connection.execute(
            "SELECT count(*) FROM artifact_payload_management_audit"
        ).fetchone()
    assert audit_count == (1,)


@pytest.mark.parametrize("persisted", [True, False])
def test_put_response_loss_is_reconciled_without_guessing(
    dsn: str,
    *,
    persisted: bool,
) -> None:
    context = _context(dsn)
    context.coordinator = CloudToolOutputArtifactCoordinator(
        context.session_id,
        context.metadata,
        cast(ArtifactObjectStorePort, _LostPutAckObjects(context.objects, persisted=persisted)),
    )
    projected = context.coordinator.output_projector.project_text(
        "uncertain put output",
        artifact_name="uncertain-put.txt",
    )
    draft = _terminal_draft(projected.model_output, projected.metadata)
    if persisted:
        context.coordinator.append_draft(
            draft,
            cast(DurableHarnessEventRecorder, context.recorder),
        )
    else:
        with pytest.raises(RuntimeError, match="lost put acknowledgement"):
            context.coordinator.append_draft(
                draft,
                cast(DurableHarnessEventRecorder, context.recorder),
            )
    artifact_id = _artifact_id(projected.metadata)
    metadata = context.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=context.namespace,
            artifact_id=artifact_id,
            session_id=context.session_id,
        )
    )
    assert metadata is not None
    expected_status = (
        CloudArtifactPayloadLifecycleStatus.FINALIZED
        if persisted
        else CloudArtifactPayloadLifecycleStatus.COMPENSATED
    )
    assert metadata.lifecycle_status is expected_status


def test_lost_event_ack_keeps_staged_payload_for_management_finalize(dsn: str) -> None:
    context = _context(dsn, fail_after_event_commit=True)
    projected = context.coordinator.output_projector.project_text(
        "recoverable output",
        artifact_name="tests-run.txt",
    )
    with pytest.raises(RuntimeError, match="lost Event acknowledgement"):
        context.coordinator.append_draft(
            _terminal_draft(projected.model_output, projected.metadata),
            cast(DurableHarnessEventRecorder, context.recorder),
        )
    artifact_id = _artifact_id(projected.metadata)
    query = ArtifactMetadataQuery(
        deployment_namespace=context.namespace,
        artifact_id=artifact_id,
        session_id=context.session_id,
    )
    staged = context.metadata.get_metadata(query)
    event = context.events.list_for_session(context.session_id)[1]

    assert staged is not None
    assert staged.lifecycle_status is CloudArtifactPayloadLifecycleStatus.STAGED
    assert staged.object_receipt is not None
    finalized = context.metadata.finalize_reconciled(
        ArtifactFinalizeRequest(
            artifact_id=artifact_id,
            session_id=context.session_id,
            expected_lifecycle_revision=1,
            idempotency_key=f"management-finalize:{artifact_id}",
            event_binding=ArtifactEventBinding(
                session_id=context.session_id,
                event_id=event.event_id,
                sequence=event.sequence,
                artifact_uri=f"artifact://{artifact_id}",
            ),
            object_receipt=staged.object_receipt,
            finalized_at=datetime.now(UTC),
        ),
        authority=AdministrativeMutationCAS(
            deployment_namespace=context.namespace,
            session_id=context.session_id,
            expected_stream_revision=1,
        ),
        audit=ArtifactManagementContext(
            operation_id=uuid4(),
            operator_id="artifact-reconciler",
            reason="recover lost terminal Event acknowledgement",
        ),
    )
    assert finalized.lifecycle_status is CloudArtifactPayloadLifecycleStatus.FINALIZED


def test_finalize_failure_keeps_committed_event_and_verified_staged_object(dsn: str) -> None:
    context = _context(dsn)
    context.coordinator = CloudToolOutputArtifactCoordinator(
        context.session_id,
        cast(Any, _FailFinalizeMetadata(context.metadata)),
        context.objects,
    )
    projected = context.coordinator.output_projector.project_text(
        "finalize recovery evidence",
        artifact_name="finalize-failure.txt",
    )
    with pytest.raises(RuntimeError, match="finalize rejected"):
        context.coordinator.append_draft(
            _terminal_draft(projected.model_output, projected.metadata),
            cast(DurableHarnessEventRecorder, context.recorder),
        )
    artifact_id = _artifact_id(projected.metadata)
    metadata = context.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=context.namespace,
            artifact_id=artifact_id,
            session_id=context.session_id,
        )
    )
    assert metadata is not None
    assert metadata.lifecycle_status is CloudArtifactPayloadLifecycleStatus.STAGED
    assert metadata.object_receipt is not None
    assert len(context.events.list_for_session(context.session_id)) == 2


def test_event_sequence_drift_leaves_staged_evidence_without_append(dsn: str) -> None:
    context = _context(dsn, drift_on_prepare=True)
    projected = context.coordinator.output_projector.project_text(
        "drift recovery evidence",
        artifact_name="sequence-drift.txt",
    )
    with pytest.raises(ValueError, match="Event sequence changed"):
        context.coordinator.append_draft(
            _terminal_draft(projected.model_output, projected.metadata),
            cast(DurableHarnessEventRecorder, context.recorder),
        )
    artifact_id = _artifact_id(projected.metadata)
    metadata = context.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=context.namespace,
            artifact_id=artifact_id,
            session_id=context.session_id,
        )
    )
    assert metadata is not None
    assert metadata.lifecycle_status is CloudArtifactPayloadLifecycleStatus.STAGED
    assert metadata.object_receipt is not None
    assert len(context.events.list_for_session(context.session_id)) == 2


def test_rejected_event_keeps_staged_object_for_safe_reconcile(dsn: str) -> None:
    context = _context(dsn, fail_before_event_commit=True)
    projected = context.coordinator.output_projector.project_text(
        "must be compensated",
        artifact_name="command-run.txt",
    )
    with pytest.raises(RuntimeError, match="Event append rejected"):
        context.coordinator.append_draft(
            _terminal_draft(projected.model_output, projected.metadata),
            cast(DurableHarnessEventRecorder, context.recorder),
        )
    artifact_id = _artifact_id(projected.metadata)
    metadata = context.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=context.namespace,
            artifact_id=artifact_id,
            session_id=context.session_id,
        )
    )
    assert metadata is not None
    assert metadata.lifecycle_status is CloudArtifactPayloadLifecycleStatus.STAGED
    assert len(context.events.list_for_session(context.session_id)) == 1
    expectation = ArtifactObjectExpectation(
        deployment_namespace=context.namespace,
        artifact_id=artifact_id,
        sha256=metadata.reservation.sha256,
        size_bytes=metadata.reservation.size_bytes,
    )
    assert context.objects.verify(expectation).status.value == "verified"


def test_uncaptured_managed_uri_fails_closed_before_event_append(dsn: str) -> None:
    context = _context(dsn)
    draft = _terminal_draft(
        "untrusted",
        {"artifact_uri": f"artifact://{uuid4()}"},
    )

    with pytest.raises(ValueError, match="no captured payload"):
        context.coordinator.append_draft(
            draft,
            cast(DurableHarnessEventRecorder, context.recorder),
        )
    assert len(context.events.list_for_session(context.session_id)) == 1


def test_external_artifact_uri_bypasses_managed_object_lifecycle(dsn: str) -> None:
    context = _context(dsn)
    event = context.coordinator.append_draft(
        _terminal_draft("external", {"artifact_uri": "https://example.com/result.txt"}),
        cast(DurableHarnessEventRecorder, context.recorder),
    )

    assert event.sequence == 1
    with psycopg.connect(dsn) as connection:
        count = connection.execute("SELECT count(*) FROM artifact_payload_metadata").fetchone()
    assert count == (0,)


class _Recorder:
    def __init__(
        self,
        events: PostgresEventStore,
        authority: WorkerMutationAuthority,
        *,
        drift_on_prepare: bool,
        fail_before_event_commit: bool,
        fail_after_event_commit: bool,
    ) -> None:
        self._events = events
        self.worker_mutation_authority = authority
        self.drift_on_prepare = drift_on_prepare
        self.fail_before_event_commit = fail_before_event_commit
        self.fail_after_event_commit = fail_after_event_commit

    @property
    def next_sequence(self) -> int:
        return self.worker_mutation_authority.expected_stream_revision + 1

    def prepare(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        *,
        created_at: datetime | None = None,
    ) -> SessionEvent:
        if self.drift_on_prepare:
            drift = SessionEvent.create(
                session_id=self.worker_mutation_authority.session_id,
                sequence=self.next_sequence,
                event_type=EventType.HARNESS_ATTEMPT_STARTED,
                actor=EventActor.HARNESS,
                payload={"attempt_number": 1},
                created_at=datetime.now(UTC),
            )
            self._events.append(drift)
            self.worker_mutation_authority = self.worker_mutation_authority.model_copy(
                update={"expected_stream_revision": drift.sequence}
            )
        return SessionEvent.create(
            session_id=self.worker_mutation_authority.session_id,
            sequence=self.next_sequence,
            event_type=event_type,
            actor=actor,
            payload=payload,
            created_at=created_at or datetime.now(UTC),
        )

    def append_event(self, event: SessionEvent) -> SessionEvent:
        if self.fail_before_event_commit:
            raise RuntimeError("Event append rejected")
        persisted = self._events.append(event)
        if self.fail_after_event_commit:
            raise RuntimeError("lost Event acknowledgement")
        self.worker_mutation_authority = self.worker_mutation_authority.model_copy(
            update={"expected_stream_revision": event.sequence}
        )
        return persisted

    def append_draft(self, draft: HarnessEventDraft) -> SessionEvent:
        return self.append_event(self.prepare(draft.event_type, draft.actor, draft.payload))


class _LostPutAckObjects:
    def __init__(self, delegate: S3ArtifactObjectStore, *, persisted: bool) -> None:
        self._delegate = delegate
        self._persisted = persisted

    def put_if_absent(self, request: Any) -> Any:
        if self._persisted:
            self._delegate.put_if_absent(request)
        raise RuntimeError("lost put acknowledgement")

    def verify(self, expectation: ArtifactObjectExpectation) -> Any:
        return self._delegate.verify(expectation)


class _FailFinalizeMetadata:
    def __init__(self, delegate: PostgresCloudArtifactPayloadStore) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def finalize_for_worker(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("finalize rejected")


class _Context:
    def __init__(
        self,
        namespace: str,
        session_id: SessionId,
        events: PostgresEventStore,
        metadata: PostgresCloudArtifactPayloadStore,
        objects: S3ArtifactObjectStore,
        recorder: _Recorder,
    ) -> None:
        self.namespace = namespace
        self.session_id = session_id
        self.events = events
        self.metadata = metadata
        self.objects = objects
        self.recorder = recorder
        self.coordinator = CloudToolOutputArtifactCoordinator(
            session_id,
            metadata,
            objects,
        )


def _context(
    dsn: str,
    *,
    drift_on_prepare: bool = False,
    fail_before_event_commit: bool = False,
    fail_after_event_commit: bool = False,
) -> _Context:
    namespace = f"tool-output-{uuid4()}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    session_id = new_session_id()
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "Tool output Artifact"},
            created_at=datetime.now(UTC),
        )
    )
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id,
        owner_instance_id="tool-output-worker",
        ttl=timedelta(minutes=5),
    )
    authority = WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=session_id,
        expected_stream_revision=0,
        lease_fence=lease.fence,
    )
    return _Context(
        namespace,
        session_id,
        events,
        PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace),
        S3ArtifactObjectStore(_s3_client(), bucket=_bucket()),
        _Recorder(
            events,
            authority,
            drift_on_prepare=drift_on_prepare,
            fail_before_event_commit=fail_before_event_commit,
            fail_after_event_commit=fail_after_event_commit,
        ),
    )


def _s3_client() -> Any:
    endpoint = os.environ.get("ZEBRA_TEST_S3_ENDPOINT")
    access_key = os.environ.get("ZEBRA_TEST_S3_ACCESS_KEY")
    secret_key = os.environ.get("ZEBRA_TEST_S3_SECRET_KEY")
    if not endpoint or not access_key or not secret_key:
        pytest.skip("set ZEBRA_TEST_S3_* variables to run MinIO tests")
    return Session().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _bucket() -> str:
    return os.environ.get("ZEBRA_TEST_S3_BUCKET", "zebra-artifacts")


def _terminal_draft(
    output: str,
    metadata: dict[str, object],
    *,
    event_type: EventType = EventType.TOOL_EXECUTION_COMPLETED,
    status: str = "executed",
) -> HarnessEventDraft:
    return HarnessEventDraft(
        event_type=event_type,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "command.run",
            "status": status,
            "output": output,
            "metadata": metadata,
        },
    )


def _artifact_id(metadata: dict[str, object]) -> ArtifactId:
    uri = cast(str, metadata["artifact_uri"])
    return ArtifactId(UUID(uri.removeprefix("artifact://")))
