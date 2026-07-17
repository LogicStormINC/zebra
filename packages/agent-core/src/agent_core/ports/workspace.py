from pathlib import Path
from typing import Protocol


class WorkspacePort(Protocol):
    @property
    def root_path(self) -> Path: ...

    def ensure(self) -> object: ...

    def resolve_path(self, relative_path: str | Path) -> Path: ...
