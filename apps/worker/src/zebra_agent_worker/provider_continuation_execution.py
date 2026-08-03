"""Worker composition helpers for cloud Provider Continuation."""

from collections.abc import Callable

from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports import (
    ContextLifecycleStorePort,
    EventStorePort,
    ProviderContinuationStorePort,
    WorkerProjectionTransactionPort,
)

from zebra_agent_worker.context_lifecycle import (
    persist_provider_continuation,
    recover_provider_continuation,
)
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.provider_continuation_commit import (
    CloudProviderContinuationCoordinator,
)
from zebra_agent_worker.tool_output_artifact_runtime import persist_worker_event
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator

CloudProviderContinuationFactory = Callable[[SessionId], CloudProviderContinuationCoordinator]


def validate_factory(
    factory: CloudProviderContinuationFactory | None,
    transaction: WorkerProjectionTransactionPort | None,
    deployment_namespace: str | None,
) -> CloudProviderContinuationFactory | None:
    if factory is not None and (transaction is None or deployment_namespace is None):
        raise ValueError(
            "cloud Provider Continuation requires the fenced Worker projection transaction"
        )
    return factory


def cloud_for_session(
    factory: CloudProviderContinuationFactory | None,
    session_id: SessionId,
) -> CloudProviderContinuationCoordinator | None:
    return factory(session_id) if factory is not None else None


def artifact_for(
    factory: Callable[[SessionId], CloudToolOutputArtifactCoordinator] | None,
    session_id: SessionId,
) -> CloudToolOutputArtifactCoordinator | None:
    return factory(session_id) if factory is not None else None


def resolve_provider_continuation(
    coordinator: CloudProviderContinuationCoordinator | None,
    events: list[SessionEvent],
    local_store: ProviderContinuationStorePort,
) -> ProviderContinuationRef | None:
    if coordinator is not None:
        return coordinator.recover(events)
    return recover_provider_continuation(events, local_store)


def build_provider_continuation_preparer(
    coordinator: CloudProviderContinuationCoordinator | None,
    local_store: ProviderContinuationStorePort,
    session_id: SessionId,
) -> Callable[[ProviderContinuationRef, bytes | None, int | None], str | None]:
    def prepare(
        reference: ProviderContinuationRef,
        payload: bytes | None,
        maximum_ttl_seconds: int | None,
    ) -> str | None:
        if coordinator is not None:
            return coordinator.prepare(reference, payload, maximum_ttl_seconds)
        return persist_provider_continuation(
            local_store,
            session_id,
            reference,
            payload,
            maximum_ttl_seconds,
        )

    return prepare


def build_worker_event_persister(
    coordinator: CloudProviderContinuationCoordinator | None,
    *,
    recorder: DurableHarnessEventRecorder,
    event_store: EventStorePort,
    lifecycle_store: ContextLifecycleStorePort,
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
) -> Callable[[HarnessEventDraft], None]:
    def persist(draft: HarnessEventDraft) -> None:
        if coordinator is not None and draft.event_type is EventType.CONTEXT_CONTINUATION_SELECTED:
            coordinator.append_draft(draft, recorder)
            return
        persist_worker_event(
            draft,
            recorder=recorder,
            event_store=event_store,
            lifecycle_store=lifecycle_store,
            cloud_artifacts=cloud_artifacts,
        )

    return persist


def build_worker_context_sinks(
    coordinator: CloudProviderContinuationCoordinator | None,
    *,
    recorder: DurableHarnessEventRecorder,
    event_store: EventStorePort,
    lifecycle_store: ContextLifecycleStorePort,
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
    local_store: ProviderContinuationStorePort,
    session_id: SessionId,
) -> tuple[
    Callable[[HarnessEventDraft], None],
    Callable[[ProviderContinuationRef, bytes | None, int | None], str | None],
]:
    return (
        build_worker_event_persister(
            coordinator,
            recorder=recorder,
            event_store=event_store,
            lifecycle_store=lifecycle_store,
            cloud_artifacts=cloud_artifacts,
        ),
        build_provider_continuation_preparer(coordinator, local_store, session_id),
    )
