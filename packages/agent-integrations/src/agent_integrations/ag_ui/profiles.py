"""Explicit projector bindings; absent binding always retains the legacy path.

Bindings are reconstructed from immutable source coordinates, never inferred from
historical text or written by stream GETs. Production has no 1.0 producer yet.
"""

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader

from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.projection import AgUiProjector
from agent_integrations.ag_ui.projection_state import ProjectionState

PROFILE_IDS = ("agui-standard-1.0", "zebra-reliable-v2-agui-1.0")


@dataclass(frozen=True, slots=True)
class AgUiProjectionProfile:
    profile_id: str
    projector: AgUiProjector
    revision: int = 1
    state_type: type[ProjectionState] = ProjectionState

    def __post_init__(self) -> None:
        if (
            self.profile_id not in PROFILE_IDS
            or type(self.revision) is not int
            or not 1 <= self.revision <= 999
        ):
            raise AgUiProjectionError("unsupported AG-UI profile/revision")
        if not isinstance(self.state_type, type) or not issubclass(
            self.state_type, ProjectionState
        ):
            raise AgUiProjectionError("profile requires a restorable projection state")
        if not isinstance(self.projector, AgUiProjector):
            raise AgUiProjectionError("profile requires a bound projector")

    def checkpoint_version(self, *, coverage: bool = False) -> str:
        return f"{self.profile_id}:r{self.revision}" + (":coverage" if coverage else "")

    def binding_digest(self, scope: ProjectionScope, run: TaskRunHeader) -> str:
        if (
            run.anchor is None
            or run.legacy
            or run.control_only
            or scope.task_id != run.task_id
            or scope.anchor_event_id != run.anchor.event_id
            or scope.projector_version != self.checkpoint_version(coverage=run.strict_coverage)
        ):
            raise AgUiProjectionError("profile has no exact durable Run binding")
        return _digest(
            [
                "zebra:agui:binding:1",
                scope.namespace,
                str(run.task_id),
                run.run_id,
                self.profile_id,
                self.revision,
                scope.projector_version,
                str(run.anchor.event_id),
            ]
        )

    def protocol_run_id(
        self,
        source: AgentTaskPort,
        scope: ProjectionScope,
        run: TaskRunHeader,
        continuation: TaskEventHeader,
    ) -> str:
        binding = self.binding_digest(scope, run)
        if (
            source.read_event_header(run.task_id, run.start) != run.anchor
            or source.read_event_header(run.task_id, continuation.task_sequence) != continuation
        ):
            raise AgUiProjectionError("protocol Run anchor is not canonical")
        if continuation != run.anchor and (
            continuation.task_id != run.task_id
            or continuation.event_type is not EventType.SESSION_COMMAND_ACCEPTED
            or not continuation.internal_continuation
            or continuation.command_run_id != run.run_id
            or not run.start < continuation.task_sequence <= run.highwater
            or (run.stop is not None and continuation.task_sequence >= run.stop)
        ):
            raise AgUiProjectionError("protocol Run requires an immutable continuation anchor")
        return "agui:" + _digest(["zebra:agui:protocol-run:1", binding, str(continuation.event_id)])


class AgUiProfileRegistry:
    def __init__(self, profiles: tuple[AgUiProjectionProfile, ...] = ()) -> None:
        self._profiles = {profile.profile_id: profile for profile in profiles}
        if len(self._profiles) != len(profiles):
            raise AgUiProjectionError("duplicate AG-UI profile binding")

    @property
    def available_profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    def select(self, requested: str | None) -> AgUiProjectionProfile | None:
        if requested is None:
            return None
        if requested not in self._profiles:
            raise AgUiProjectionError("AG-UI profile is unsupported or unavailable")
        return self._profiles[requested]


def _digest(value: list[object]) -> str:
    return sha256(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def is_profile_version(version: str) -> bool:
    return any(
        re.fullmatch(re.escape(name) + r":r[1-9][0-9]{0,2}(?::coverage)?", version)
        for name in PROFILE_IDS
    )
