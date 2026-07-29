"""Composition helpers for the optional cloud Tool-output Artifact path."""

from collections.abc import Callable

from agent_core.domain.identifiers import SessionId
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports import (
    ContextLifecycleStorePort,
    EffectDispatchPort,
    EventStorePort,
    WorkerProjectionTransactionPort,
)

from zebra_agent_worker.context_lifecycle import persist_context_compaction
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator

CloudArtifactCoordinatorFactory = Callable[
    [SessionId],
    CloudToolOutputArtifactCoordinator,
]


def validate_cloud_artifact_factory(
    factory: CloudArtifactCoordinatorFactory | None,
    transaction: WorkerProjectionTransactionPort | None,
    deployment_namespace: str | None,
    effect_dispatch: EffectDispatchPort | None,
) -> CloudArtifactCoordinatorFactory | None:
    if factory is not None and (transaction is None or deployment_namespace is None):
        raise ValueError(
            "cloud Artifact output requires the fenced Worker projection transaction"
        )
    if factory is not None and effect_dispatch is not None:
        required = (
            "schedule_with_payload",
            "complete_with_payload",
            "mark_uncertain_with_payload",
        )
        if any(not callable(getattr(effect_dispatch, name, None)) for name in required):
            raise ValueError(
                "cloud Artifact output with fenced Effect dispatch requires atomic payload linkage"
            )
    return factory


def persist_worker_event(
    draft: HarnessEventDraft,
    *,
    recorder: DurableHarnessEventRecorder,
    event_store: EventStorePort,
    lifecycle_store: ContextLifecycleStorePort,
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
) -> None:
    from agent_core.domain.events import EventType

    if draft.event_type is EventType.CONTEXT_COMPACTED:
        persist_context_compaction(
            draft,
            recorder=recorder,
            event_store=event_store,
            lifecycle_store=lifecycle_store,
        )
    elif cloud_artifacts is None:
        recorder.append_draft(draft)
    else:
        cloud_artifacts.append_draft(draft, recorder)
