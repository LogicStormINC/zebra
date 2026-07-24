from dataclasses import dataclass
from typing import Protocol, TypedDict

from agent_core.domain.identifiers import SessionId


class PreviewState(TypedDict):
    redacted: bool
    truncated: bool


@dataclass(frozen=True)
class SessionArtifact:
    artifact_id: str
    session_id: SessionId
    sequence: int
    source: str
    kind: str
    label: str
    uri: str | None
    preview: str
    preview_state: PreviewState
    metadata: dict[str, object]


class SessionArtifactReadPort(Protocol):
    def list_for_session(self, session_id: SessionId) -> list[SessionArtifact]: ...
