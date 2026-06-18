from agent_core.ports.runtime import RuntimePort


class LocalRuntime(RuntimePort):
    def execute(self, command: list[str]) -> int:
        return 0 if command else 1
