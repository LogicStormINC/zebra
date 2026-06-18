from agent_core.domain.sessions import SessionStatus


def worker_banner() -> str:
    return f"worker-ready:{SessionStatus.CREATED.value}"
