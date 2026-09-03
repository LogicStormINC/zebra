"""Finish one durable reply before background Cloud side effects."""

from datetime import datetime
from typing import Any

from agent_core.domain.identifiers import SessionId
from agent_core.domain.turns import InteractionMode

from zebra_agent_worker.execution_finalization import (
    ExecutedSession,
    WorkerExecutionError,
    finalize_execution,
    rebuild_task_index,
)


def finish_execution(
    *,
    recorder: Any,
    attempt_result: Any,
    memory_extraction_service: Any,
    memory_promotion_service: Any,
    title_service: Any,
    event_store: Any,
    cloud_memory_store: Any,
    deployment_namespace: str | None,
    projection_store: Any,
    workspace_store: Any,
    task_index_store: Any,
    session_id: SessionId,
    started_at: datetime,
    interaction_mode: InteractionMode,
) -> ExecutedSession:
    events = finalize_execution(
        recorder=recorder,
        attempt_result=attempt_result,
        memory_extraction_service=memory_extraction_service,
        memory_promotion_service=memory_promotion_service,
        title_service=title_service,
        event_store=event_store,
        cloud_memory_store=cloud_memory_store,
        deployment_namespace=deployment_namespace,
        projection_store=projection_store,
        workspace_store=workspace_store,
        started_at=started_at,
        interaction_mode=interaction_mode,
        defer_cloud_side_effects=cloud_memory_store is not None,
    )
    session = projection_store.get_session(session_id)
    if session is None:
        raise WorkerExecutionError("session projection missing after worker execution")
    rebuild_task_index(task_index_store, session_id)
    return ExecutedSession(session, events, attempt_result)
