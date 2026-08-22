"""Agent team tests: bounds, depth, shared list, write exclusivity."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agent_core.domain.identifiers import TaskId
from agent_orchestration.domain.agent_team import (
    MAX_TEAM_AGENTS,
    AgentTeam,
    TeamContractError,
    TeamTaskAssignment,
    assert_write_depth_one,
)
from agent_orchestration.domain.worktree_orchestration import WorktreeOwnership
from pydantic import ValidationError


def _ownership(task_id: TaskId, paths: tuple[str, ...]) -> WorktreeOwnership:
    return WorktreeOwnership(
        worktree_id=f"wt-{uuid4().hex[:8]}",
        child_task_id=task_id,
        base_revision="rev-1",
        branch_ref="refs/heads/zebra/team",
        owned_paths=paths,
        workspace_quota_bytes=1_048_576,
        runtime_spec_digest="d" * 64,
    )


def _team(
    *,
    teammates: tuple[str, ...] = ("mate-1",),
    tasks: tuple[TeamTaskAssignment, ...] = (),
    ownerships: tuple[WorktreeOwnership, ...] = (),
) -> AgentTeam:
    from agent_orchestration.domain.agent_team import validate_team

    return validate_team(
        AgentTeam(
            team_id="team-1",
            namespace_id="tenant-a",
            lead="lead",
            teammates=teammates,
            shared_tasks=tasks,
            write_ownerships=ownerships,
        )
    )


class TestBounds:
    def test_four_agents_is_the_ceiling(self) -> None:
        assert MAX_TEAM_AGENTS == 4
        assert len(_team(teammates=("m1", "m2", "m3")).members) == 4
        with pytest.raises(TeamContractError, match="bounded to 4"):
            _team(teammates=("m1", "m2", "m3", "m4"))

    def test_members_must_be_unique(self) -> None:
        with pytest.raises(TeamContractError, match="unique"):
            _team(teammates=("lead",))

    def test_depth_is_one_and_enforced(self) -> None:
        team = _team()
        assert team.depth == 1
        assert_write_depth_one(0)
        with pytest.raises(TeamContractError, match="depth is one"):
            assert_write_depth_one(1)


class TestSharedTaskList:
    def test_assignments_must_target_members(self) -> None:
        task_id = TaskId(uuid4())
        assignment = TeamTaskAssignment(
            task_id=task_id, node_key="n1", assignee="outsider", status="open"
        )
        with pytest.raises(TeamContractError, match="non-member"):
            _team(tasks=(assignment,))

    def test_assignment_status_is_bounded(self) -> None:
        with pytest.raises(ValidationError, match="unknown"):
            TeamTaskAssignment(
                task_id=TaskId(uuid4()), node_key="n1", assignee="m", status="wat"
            )

    def test_team_digest_is_stable(self) -> None:
        first = _team()
        assert first.team_digest == _team().team_digest
        bigger = _team(teammates=("m1", "m2"))
        assert first.team_digest != bigger.team_digest


class TestWriteExclusivity:
    def test_write_tasks_hold_disjoint_owned_paths(self) -> None:
        task_a, task_b = TaskId(uuid4()), TaskId(uuid4())
        team = _team(
            teammates=("m1", "m2"),
            tasks=(
                TeamTaskAssignment(task_id=task_a, node_key="a", assignee="m1", status="claimed"),
                TeamTaskAssignment(task_id=task_b, node_key="b", assignee="m2", status="claimed"),
            ),
            ownerships=(
                _ownership(task_a, ("apps/api/",)),
                _ownership(task_b, ("apps/worker/",)),
            ),
        )
        assert len(team.write_ownerships) == 2

    def test_overlapping_write_claims_reject_the_team(self) -> None:
        task_a, task_b = TaskId(uuid4()), TaskId(uuid4())
        with pytest.raises(TeamContractError, match="conflict"):
            _team(
                teammates=("m1", "m2"),
                tasks=(
                    TeamTaskAssignment(
                        task_id=task_a, node_key="a", assignee="m1", status="claimed"
                    ),
                    TeamTaskAssignment(
                        task_id=task_b, node_key="b", assignee="m2", status="claimed"
                    ),
                ),
                ownerships=(
                    _ownership(task_a, ("apps/api/",)),
                    _ownership(task_b, ("apps/api/routes.py",)),
                ),
            )

    def test_ownership_must_reference_a_shared_task(self) -> None:
        orphan = TaskId(uuid4())
        with pytest.raises(TeamContractError, match="outside the shared list"):
            _team(ownerships=(_ownership(orphan, ("apps/api/",)),))
