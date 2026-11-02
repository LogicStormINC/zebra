"""Fenced classification of setup failure and uncertain isolated executor loss."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.plugin_authority import PLUGIN_UNAVAILABLE
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports import EventStorePort

from zebra_agent_worker.execution_errors import (
    WorkerAuthoritySetupUnavailable,
    WorkerExecutionError,
    WorkerExecutorInterrupted,
    WorkerInputPreparationUnavailable,
    WorkerPluginSetupUnavailable,
)
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_turn_close import append_turn_close

if TYPE_CHECKING:
    from zebra_agent_worker.execution_finalization import ExecutedSession


def finalize_worker_setup_failure(
    *,
    recorder: DurableHarnessEventRecorder,
    event_store: EventStorePort,
    error: WorkerExecutionError,
    attempt_number: int = 1,
) -> ExecutedSession:
    """Close known setup failure or suspend uncertain executor loss under its fence."""
    from zebra_agent_worker.execution_finalization import ExecutedSession, RuntimeStartupError

    plugin_stop = isinstance(error, WorkerPluginSetupUnavailable)
    executor_stop = isinstance(error, WorkerExecutorInterrupted)
    input_stop = isinstance(error, WorkerInputPreparationUnavailable)
    suspended_stop = (
        plugin_stop
        or executor_stop
        or input_stop
        or isinstance(error, WorkerAuthoritySetupUnavailable)
    )
    stop_reason = (
        error.reason_code
        if isinstance(error, WorkerAuthoritySetupUnavailable)
        else (
            "execution_input_unavailable"
            if input_stop
            else "executor_process_interrupted"
            if executor_stop
            else PLUGIN_UNAVAILABLE
            if plugin_stop
            else "worker_setup_failed"
        )
    )
    result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.SUSPENDED if suspended_stop else HarnessAttemptOutcome.FAILED,
        summary=(
            "沙箱执行环境不可用，任务尚未开始。请检查沙箱运行时配置后重试。"
            if isinstance(error, RuntimeStartupError)
            else "执行输入或工作区准备不可用，未进入模型执行；不会自动重新执行。"
            if input_stop
            else "执行进程意外结束，已有内容保留，等待确认；不会自动重新执行。"
            if executor_stop
            else "Worker execution could not start."
        ),
        metadata={
            "stop_reason": stop_reason,
            **({"retryable": False} if suspended_stop else {}),
            "error_type": type(error).__name__,
            "error_code": (
                "execution_input_unavailable"
                if input_stop
                else "executor_process_interrupted"
                if executor_stop
                else "runtime_unavailable"
                if isinstance(error, RuntimeStartupError)
                else "worker_setup_failed"
            ),
            **(
                {"coverage_refusal_reason": error.coverage_refusal_reason.value}
                if error.coverage_refusal_reason is not None
                else {}
            ),
        },
    )
    if recorder.session.status is SessionStatus.READY:
        recorder.append(
            EventType.HARNESS_ATTEMPT_STARTED,
            EventActor.HARNESS,
            {"attempt_number": attempt_number},
        )
    if suspended_stop:
        recorder.append(
            EventType.SESSION_SUSPENDED,
            EventActor.HARNESS,
            {"reason": stop_reason, "metadata": result.metadata},
        )
        return ExecutedSession(recorder.session, recorder.events, result)
    append_turn_close(
        recorder=recorder,
        attempt_result=result,
        event_store=event_store,
        interaction_mode=InteractionMode.CONVERSATION,
        attempt_number=attempt_number,
    )
    return ExecutedSession(recorder.session, recorder.events, result)
