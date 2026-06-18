from typing import Protocol


class RuntimePort(Protocol):
    def execute(self, command: list[str]) -> int: ...
