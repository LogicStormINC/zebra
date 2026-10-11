from dataclasses import dataclass
from typing import Protocol, TypedDict
from uuid import UUID

from agent_core.domain.identifiers import EventId, SessionId


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
    source_event_id: EventId | None = None


class SessionArtifactReadPort(Protocol):
    def list_for_session(self, session_id: SessionId) -> list[SessionArtifact]: ...

    def get_for_session(self, session_id: SessionId, artifact_id: str) -> SessionArtifact | None:
        """Read exactly one canonical projection or bound payload UUID; never list."""
        ...


MAX_ARTIFACT_PROJECTION_BYTES = 1_048_576


class SessionArtifactReadUnavailableError(RuntimeError):
    """The selected projection cannot be read safely within its resource bound."""


def parse_session_artifact_id(value: str) -> tuple[str, int] | UUID | None:
    """Keep both adapters on canonical, bounded identity parsing."""
    if len(value) > 36:
        return None
    if ":" in value:
        source, sequence = value.split(":", 1)
        if source not in {"model-call", "tool-run"} or not sequence.isascii():
            return None
        if not sequence.isdecimal() or (len(sequence) > 1 and sequence.startswith("0")):
            return None
        number = int(sequence)
        return (source, number) if number <= 9_223_372_036_854_775_807 else None
    try:
        public_id = UUID(value)
    except ValueError:
        return None
    return public_id if str(public_id) == value else None
