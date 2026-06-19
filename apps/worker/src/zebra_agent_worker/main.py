from agent_core.domain.sessions import SessionStatus

from zebra_agent_worker.recovery import SessionRecoveryService


def worker_banner() -> str:
    return f"worker-ready:{SessionStatus.CREATED.value}"


__all__ = [
    "SessionRecoveryService",
    "worker_banner",
]
