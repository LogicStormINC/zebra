"""Client run bindings: task run × client session with narrowed capability.

ADR-CLIENT-01: the binding is separate from the host TaskBindingSnapshot,
pins the profile and mounted-snapshot digests for the whole run, and its
revision only ever increases while capabilities only ever narrow.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.identifiers import (
    ClientRunBindingId,
    ClientSessionId,
    TaskId,
)


class ClientRunBindingError(ValueError):
    pass


class ClientBindingNarrowingError(ClientRunBindingError):
    pass


def client_run_binding_key(task_id: TaskId, run_id: str, client_session_id: ClientSessionId) -> str:
    return f"{task_id}:{run_id}:{client_session_id}"


class ClientRunBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: ClientRunBindingId
    task_id: TaskId
    run_id: str = Field(min_length=1, max_length=128)
    client_session_id: ClientSessionId
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mounted_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_capability_scope: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    binding_revision: int = Field(ge=1)
    created_at: datetime

    @model_validator(mode="after")
    def _check_narrowing(self) -> ClientRunBinding:
        if len(set(self.allowed_actions)) != len(self.allowed_actions):
            raise ClientRunBindingError("allowed actions must be unique")
        scope = set(self.task_capability_scope)
        escaped = set(self.allowed_actions) - scope
        if escaped:
            raise ClientBindingNarrowingError(
                f"client actions outside the task capability scope: {sorted(escaped)}"
            )
        return self

    @property
    def binding_digest(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"binding_revision", "created_at"},
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def narrow(
        self,
        *,
        mounted_actions: tuple[str, ...],
        revision_reason: str,
    ) -> ClientRunBinding:
        """Produce the next revision; capabilities may only shrink."""

        remaining = tuple(
            action
            for action in self.allowed_actions
            if action in set(mounted_actions)
        )
        if set(remaining) - set(self.allowed_actions):
            raise ClientBindingNarrowingError("narrowing cannot add capabilities")
        return self.model_copy(
            update={
                "allowed_actions": remaining,
                "mounted_snapshot_digest": self.mounted_snapshot_digest,
                "binding_revision": self.binding_revision + 1,
            }
        )

    def ensure_allows(self, action_name: str) -> None:
        if action_name not in set(self.allowed_actions):
            raise ClientBindingNarrowingError(
                f"action {action_name} is not allowed by this client run binding"
            )
