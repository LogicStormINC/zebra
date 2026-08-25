"""Client session admission and runtime binding services (ADR-CLIENT-01).

Admission converts a Host-BFF grant into a durable client session;
binding narrows the task capability scope through the mounted snapshot
and pins digests for the whole run; the control lease enforces one
active controller per run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent_core.domain.client_capabilities import (
    MountedCapabilityNarrowingError,
    MountedCapabilitySnapshot,
)
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLease,
    ClientSession,
    ClientSessionGrant,
    ClientSessionStatus,
)
from agent_core.domain.identifiers import (
    ClientSessionId,
    TaskId,
    new_client_run_binding_id,
    new_client_session_id,
)
from agent_core.ports.client_control_lease import ClientControlLeasePort
from agent_core.ports.client_session_registry import ClientSessionRegistryPort


class ClientAdmissionError(ValueError):
    pass


DEFAULT_SESSION_TTL = timedelta(hours=12)
DEFAULT_CONTROL_LEASE_TTL = timedelta(minutes=5)


@dataclass(frozen=True)
class ClientAdmission:
    session: ClientSession
    mounted_snapshot_digest: str | None


class ClientAdmissionService:
    def __init__(
        self,
        sessions: ClientSessionRegistryPort,
    ) -> None:
        self._sessions = sessions

    def open_session(
        self,
        grant: ClientSessionGrant,
        *,
        session_ttl: timedelta = DEFAULT_SESSION_TTL,
    ) -> ClientSession:
        now = datetime.now(UTC)
        session = ClientSession(
            session_id=new_client_session_id(),
            grant=grant,
            status=ClientSessionStatus.ACTIVE,
            created_at=now,
            expires_at=now + session_ttl,
        )
        self._sessions.create_session(session)
        return session

    def heartbeat(self, session_id: ClientSessionId) -> ClientSession:
        return self._sessions.heartbeat_session(
            session_id, heartbeat_at=datetime.now(UTC)
        )

    def mount(
        self,
        session_id: ClientSessionId,
        snapshot: MountedCapabilitySnapshot,
        *,
        current_allowed_actions: tuple[str, ...] | None = None,
    ) -> ClientAdmission:
        session = self._sessions.get_session(session_id)
        if session is None:
            raise ClientAdmissionError("client session not found")
        session.ensure_active()
        if session.mounted_snapshot_digest is not None:
            prior = self._sessions.get_mounted_snapshot(session_id)
            if prior is not None:
                ensure_mount_narrows(prior, snapshot)
        self._sessions.save_mounted_snapshot(snapshot)
        updated = self._sessions.get_session(session_id)
        assert updated is not None
        return ClientAdmission(
            session=updated,
            mounted_snapshot_digest=snapshot.snapshot_digest,
        )


class ClientBindingService:
    def __init__(
        self,
        sessions: ClientSessionRegistryPort,
        leases: ClientControlLeasePort,
    ) -> None:
        self._sessions = sessions
        self._leases = leases

    def bind_run(
        self,
        *,
        task_id: TaskId,
        run_id: str,
        session_id: ClientSessionId,
        task_capability_scope: tuple[str, ...],
        controller: bool = True,
        lease_ttl: timedelta = DEFAULT_CONTROL_LEASE_TTL,
    ) -> tuple[ClientRunBinding, ClientControlLease | None]:
        session = self._sessions.get_session(session_id)
        if session is None:
            raise ClientAdmissionError("client session not found")
        session.ensure_active()
        snapshot = self._sessions.get_mounted_snapshot(session_id)
        if snapshot is None:
            raise ClientAdmissionError("client session has no mounted snapshot")
        existing = self._sessions.get_run_binding(task_id, run_id, session_id)
        mounted = set(snapshot.mounted_actions)
        allowed = tuple(
            action for action in sorted(mounted & set(task_capability_scope))
        )
        if existing is None:
            binding = ClientRunBinding(
                binding_id=new_client_run_binding_id(),
                task_id=task_id,
                run_id=run_id,
                client_session_id=session_id,
                profile_digest=snapshot.profile_digest,
                mounted_snapshot_digest=snapshot.snapshot_digest,
                task_capability_scope=tuple(sorted(set(task_capability_scope))),
                allowed_actions=allowed,
                binding_revision=1,
                created_at=datetime.now(UTC),
            )
        else:
            binding = existing.narrow(mounted_actions=allowed, revision_reason="mount")
        self._sessions.save_run_binding(binding)
        lease: ClientControlLease | None = None
        if controller:
            fence = ClientControlFence.issue()
            lease = self._leases.claim_controller(
                binding.binding_id,
                task_id=task_id,
                run_id=run_id,
                client_session_id=session_id,
                fence=fence,
                ttl=lease_ttl,
            )
        return binding, lease


def ensure_mount_narrows(
    prior: MountedCapabilitySnapshot, new: MountedCapabilitySnapshot
) -> None:
    """A new mount may only narrow the previously mounted capabilities."""

    if (
        new.frontend_app_id != prior.frontend_app_id
        or new.profile_revision != prior.profile_revision
        or new.profile_digest != prior.profile_digest
    ):
        raise MountedCapabilityNarrowingError(
            "remounts must keep the same published profile"
        )
    if set(new.mounted_readables) - set(prior.mounted_readables):
        raise MountedCapabilityNarrowingError("remounts may not add readables")
    if set(new.mounted_actions) - set(prior.mounted_actions):
        raise MountedCapabilityNarrowingError("remounts may not add actions")
