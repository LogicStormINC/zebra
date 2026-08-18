from typing import Protocol

from agent_core.domain.identifiers import SessionId


class EffectStateReadPort(Protocol):
    """Read-only handoff validation facts; this is not an Effect executor."""

    def terminal_keys(self, root_session_id: SessionId) -> frozenset[str]: ...

    def has_uncertain(self, root_session_id: SessionId) -> bool: ...
