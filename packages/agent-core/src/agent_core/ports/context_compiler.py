from pathlib import Path
from typing import Protocol


class ContextCompilerPort(Protocol):
    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
    ) -> str | None: ...
