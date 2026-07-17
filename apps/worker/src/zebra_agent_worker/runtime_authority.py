from datetime import datetime

from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports.runtime import EffectiveRuntimeAuthority
from agent_runtime import LocalToolGateway

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


def persist_runtime_authority(
    recorder: DurableHarnessEventRecorder,
    authority: EffectiveRuntimeAuthority | None,
    *,
    created_at: datetime,
) -> bool:
    if authority is None or recorder.workspace.runtime_spec_digest == authority.spec_digest:
        return False
    recorder.append(
        EventType.RUNTIME_PROVISIONED,
        EventActor.SYSTEM,
        {
            "runtime_class": authority.runtime_class.value,
            "engine": authority.engine,
            "image": authority.image,
            "spec_digest": authority.spec_digest,
            "network_enforcement": authority.network_enforcement,
            "workspace_writable": authority.workspace_writable,
        },
        created_at=created_at,
    )
    return True


def close_tool_gateway(tool_gateway: LocalToolGateway) -> Exception | None:
    try:
        tool_gateway.close()
    except Exception as exc:
        return exc
    return None


def runtime_cleanup_failure_result(
    error: Exception,
    prior: HarnessAttemptResult,
) -> HarnessAttemptResult:
    return HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="runtime cleanup failed",
        metadata={
            "stop_reason": "runtime_cleanup_failed",
            "error_type": type(error).__name__,
            "model_calls_used": prior.metadata.get("model_calls_used", 0),
            "tool_calls_executed": prior.metadata.get("tool_calls_executed", 0),
        },
    )
