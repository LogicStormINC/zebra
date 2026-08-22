"""Agent Team contract (ORCH-TEAM-01, plan Phase E / section 18).

First-version teams are bounded: same deployment namespace, at most four
agents including the lead, maximum depth one (teammates spawn no
children), one shared task list, and write assignments hold mutually
exclusive owned paths.
"""

from __future__ import annotations

import hashlib
import json
from typing import Self

from agent_core.domain.identifiers import TaskId
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_orchestration.domain.worktree_orchestration import (
    WorktreeOwnership,
    assert_no_owned_path_conflicts,
)

MAX_TEAM_AGENTS = 4
TEAM_DEPTH = 1


class TeamContractError(ValueError):
    """The team violates its first-version bounds."""


class TeamTaskAssignment(BaseModel):
    """One row of the shared task list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: TaskId
    node_key: str = Field(min_length=1, max_length=128)
    assignee: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.status not in {"open", "claimed", "running", "done", "failed"}:
            raise ValueError(f"unknown task assignment status: {self.status}")
        return self


class AgentTeam(BaseModel):
    """A bounded team: one lead, teammates, shared list, write claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    team_id: str = Field(min_length=1, max_length=128)
    namespace_id: str = Field(min_length=1, max_length=512)
    lead: str = Field(min_length=1, max_length=128)
    teammates: tuple[str, ...] = Field(min_length=0)
    shared_tasks: tuple[TeamTaskAssignment, ...] = ()
    write_ownerships: tuple[WorktreeOwnership, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> Self:
        # cross-field bounds live in validate_team so failures stay typed
        return self

    @property
    def members(self) -> tuple[str, ...]:
        return (self.lead, *self.teammates)

    @property
    def depth(self) -> int:
        return TEAM_DEPTH

    @property
    def team_digest(self) -> str:
        canonical = {
            "teamId": self.team_id,
            "namespaceId": self.namespace_id,
            "lead": self.lead,
            "teammates": list(self.teammates),
            "tasks": [
                {
                    "taskId": str(assignment.task_id),
                    "assignee": assignment.assignee,
                    "status": assignment.status,
                }
                for assignment in self.shared_tasks
            ],
            "writeOwnerships": [
                ownership.worktree_id for ownership in self.write_ownerships
            ],
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def validate_team(team: AgentTeam) -> AgentTeam:
    """Enforce the first-version team bounds with typed errors."""

    members = team.members
    if len(members) > MAX_TEAM_AGENTS:
        raise TeamContractError(
            f"teams are bounded to {MAX_TEAM_AGENTS} agents, got {len(members)}"
        )
    if len(set(members)) != len(members):
        raise TeamContractError("team members must be unique")
    for assignment in team.shared_tasks:
        if assignment.assignee not in members:
            raise TeamContractError(
                f"task assigned to a non-member: {assignment.assignee}"
            )
    for ownership in team.write_ownerships:
        if all(
            assignment.task_id != ownership.child_task_id
            for assignment in team.shared_tasks
        ):
            raise TeamContractError(
                f"write ownership {ownership.worktree_id} references a task "
                "outside the shared list"
            )
    try:
        assert_no_owned_path_conflicts(team.write_ownerships)
    except ValueError as exc:
        raise TeamContractError(str(exc)) from exc
    return team


def assert_write_depth_one(teammate_children_count: int) -> None:
    """Teammates never spawn their own delegations in v1 teams."""

    if teammate_children_count > 0:
        raise TeamContractError(
            "team depth is one: teammates cannot spawn children in the first version"
        )
