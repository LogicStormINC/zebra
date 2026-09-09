"""Immutable per-turn extension persistence, never admission or execution authority."""

from typing import Protocol

from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.domain.extensions import ExtensionScope


class ExtensionSnapshotNotFoundError(LookupError):
    """Unknown and cross-scope snapshots are indistinguishable."""


class ExtensionSnapshotConflictError(RuntimeError):
    """The exact turn already has a different immutable snapshot."""


class ExtensionSnapshotIntegrityError(ValueError):
    """Stored coordinates, payload, or digest disagree with trusted inputs."""


class ExtensionSnapshotStore(Protocol):
    """Persistence only; runtime must bind a trusted digest and live authorization.

    Saving an identical snapshot is idempotent. Changed snapshots conflict.
    No production Worker or admission integration is implied by this boundary.
    """

    async def save(self, *, scope: ExtensionScope, snapshot: ExtensionSnapshot) -> None: ...

    async def get(
        self, *, scope: ExtensionScope, session_id: str, turn_id: str, expected_digest: str,
    ) -> ExtensionSnapshot:
        """Require the digest from trusted turn binding, never from the stored row."""
        ...

    async def exists(
        self, *, scope: ExtensionScope, session_id: str, turn_id: str
    ) -> bool:
        """Probe one exact coordinate without exposing an untrusted stored digest."""
        ...


class ExtensionTaskAuthorityStore(Protocol):
    """Resolve immutable root-Task authority for any execution Segment."""

    def resolve_task_ceiling(self, *, session_id: str) -> ExtensionTaskCeiling: ...
