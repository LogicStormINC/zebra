from agent_core.domain.sessions import SessionStatus


def main() -> None:
    print(f"zebra-agent CLI bootstrap ready: {SessionStatus.CREATED.value}")
