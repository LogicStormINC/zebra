from typing import Protocol

from agent_core.domain.artifacts import ArtifactRef


class ArtifactStorePort(Protocol):
    def store(self, artifact: ArtifactRef) -> ArtifactRef: ...

    def get(self, uri: str) -> ArtifactRef | None: ...
