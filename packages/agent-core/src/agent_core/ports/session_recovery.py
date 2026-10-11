"""Bounded canonical Session recovery; the index frontier never implies primary coverage."""

import json
from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority


class SessionRecoveryConflict(ValueError):
    """Recovery coordinates conflict with canonical source or durable coverage."""


@dataclass(frozen=True, slots=True)
class SessionRecoveryHead:
    highwater: int
    index_sequence: int

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.highwater, self.index_sequence)) or (
            not -1 <= self.index_sequence <= self.highwater
        ):
            raise SessionRecoveryConflict("invalid Session recovery frontier")


@dataclass(frozen=True, slots=True)
class SessionEventPage:
    session_id: SessionId
    events: tuple[SessionEvent, ...]
    after_sequence: int
    highwater: int
    byte_count: int

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not int
                for value in (self.after_sequence, self.highwater, self.byte_count)
            )
            or not -1 <= self.after_sequence <= self.highwater
            or len(self.events) > 256
            or not 0 <= self.byte_count <= 1_048_576
        ):
            raise SessionRecoveryConflict("invalid bounded Session page")
        size = sum(
            len(
                json.dumps(
                    event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
                ).encode()
            )
            for event in self.events
        )
        if size != self.byte_count:
            raise SessionRecoveryConflict("Session page byte count conflicts with source")
        for sequence, event in enumerate(self.events, self.after_sequence + 1):
            if (
                event.session_id != self.session_id
                or event.sequence != sequence
                or (sequence > self.highwater)
            ):
                raise SessionRecoveryConflict("canonical Session page has a gap or foreign Event")
        if not self.events and self.after_sequence != self.highwater:
            raise SessionRecoveryConflict("Session page omits canonical coverage")

    @property
    def next_sequence(self) -> int:
        return self.events[-1].sequence if self.events else self.after_sequence


@dataclass(frozen=True, slots=True)
class SessionRecoveryCommit:
    session: Session
    workspace: WorkspaceProjection
    index_sequence: int


class SessionRecoveryPort(Protocol):
    def read_session_recovery_head(
        self, session_id: SessionId, *, authority: WorkerMutationAuthority
    ) -> SessionRecoveryHead:
        """Fence and capture a durable highwater; retain it across incomplete slices."""
        ...

    def read_session_event_page(
        self,
        session_id: SessionId,
        after_sequence: int,
        *,
        through_sequence: int,
        limit: int = 256,
        max_bytes: int = 1_048_576,
    ) -> SessionEventPage: ...

    def commit_session_recovery_page(
        self,
        page: SessionEventPage,
        *,
        expected_index_sequence: int,
        authority: WorkerMutationAuthority,
    ) -> SessionRecoveryCommit:
        """Atomically project canonical Events, index them and CAS coverage under the fence."""
        ...
