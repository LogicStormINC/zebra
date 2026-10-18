"""Finish one durable reply before background Cloud side effects."""

import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agent_core.domain.identifiers import SessionId
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptResult, HarnessContext

from zebra_agent_worker.completion_recovery import preserve_committed_result
from zebra_agent_worker.continuation_dispatch import run_continuation
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_finalization import (
    ExecutedSession,
    WorkerExecutionError,
    finalize_execution,
    rebuild_task_index,
)
from zebra_agent_worker.runtime_authority import close_tool_gateway, runtime_cleanup_failure_result


def run_worker_continuation(
    orchestrator: Any,
    context: HarnessContext,
    *,
    continuation: Any,
    clarification: Any,
    child_wakeup: Any,
    client_effect: Any,
    release_gateway: Callable[[], Exception | None],
) -> HarnessAttemptResult:
    """Always release resources; retain the original cancellation or failure."""
    try:
        try:
            result = run_continuation(
                orchestrator,
                context,
                continuation=continuation,
                clarification=clarification,
                child_wakeup=child_wakeup,
                client_effect=client_effect,
            )
        except ExecutionInterrupted:
            raise
        except Exception as error:
            result = exception_attempt_result(
                error,
                error_metadata(error, clarification, child_wakeup or continuation),
            )
    finally:
        active_error = sys.exception()
        close_error = close_tool_gateway(orchestrator)
        try:
            gateway_error = release_gateway()
        except Exception as error:
            gateway_error = error
        if close_error is not None and gateway_error is not None:
            close_error.add_note(f"gateway cleanup also failed: {type(gateway_error).__name__}")
        if active_error is not None:
            for cleanup_failure in (close_error, gateway_error):
                if cleanup_failure is not None:
                    active_error.add_note(f"cleanup also failed: {type(cleanup_failure).__name__}")
    cleanup_error = close_error or gateway_error
    return runtime_cleanup_failure_result(cleanup_error, result) if cleanup_error else result


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
    attempt_number: int = 1,
) -> ExecutedSession:
    recorder.project_persisted_tail()
    attempt_result = preserve_committed_result(
        recorder.events, attempt_result, attempt_number=attempt_number
    )
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
        attempt_number=attempt_number,
    )
    session = projection_store.get_session(session_id)
    if session is None:
        raise WorkerExecutionError("session projection missing after worker execution")
    rebuild_task_index(task_index_store, session_id)
    return ExecutedSession(session, events, attempt_result)
