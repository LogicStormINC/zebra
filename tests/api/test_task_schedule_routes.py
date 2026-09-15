from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import (
    TaskScheduleFiringId,
    TaskScheduleId,
    manual_task_schedule_firing_id,
)
from agent_core.domain.task_schedule_authority import ScheduleAuthorityBinding, ScheduleOwner
from agent_core.domain.task_schedules import (
    ScheduleFiringStatus,
    TaskSchedule,
    TaskScheduleFiring,
)
from agent_core.ports.task_schedules import TaskScheduleConflictError
from agent_security import JwtAlgorithm, VerifiedHostGrant
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.host_auth import _required_scopes_for_request
from zebra_agent_api.http import HostGrantHttpRequest


class MemoryScheduleStore:
    deployment_namespace = "cloud"

    def __init__(self) -> None:
        self.schedules: dict[TaskScheduleId, TaskSchedule] = {}
        self.authorities: dict[TaskScheduleId, ScheduleAuthorityBinding] = {}

    def create(self, schedule: TaskSchedule, authority: ScheduleAuthorityBinding) -> TaskSchedule:
        if schedule.schedule_id in self.schedules:
            raise TaskScheduleConflictError
        self.schedules[schedule.schedule_id] = schedule
        self.authorities[schedule.schedule_id] = authority
        return schedule

    def get(self, schedule_id: TaskScheduleId, *, owner: ScheduleOwner) -> TaskSchedule | None:
        schedule = self.schedules.get(schedule_id)
        return schedule if schedule is not None and schedule.owner == owner else None

    def get_authority(
        self, schedule_id: TaskScheduleId, *, owner: ScheduleOwner
    ) -> ScheduleAuthorityBinding | None:
        schedule = self.get(schedule_id, owner=owner)
        return self.authorities.get(schedule_id) if schedule is not None else None

    def list_for_owner(self, owner: ScheduleOwner, *, limit: int) -> tuple[TaskSchedule, ...]:
        return tuple(item for item in self.schedules.values() if item.owner == owner)[:limit]

    def revoke_authority(
        self, authority: ScheduleAuthorityBinding, *, expected_revision: int
    ) -> ScheduleAuthorityBinding:
        current = self.authorities.get(authority.schedule_id)
        if current is None or current.binding_revision != expected_revision:
            raise TaskScheduleConflictError
        self.authorities[authority.schedule_id] = authority
        return authority

    def update(self, schedule: TaskSchedule, *, expected_version: int) -> TaskSchedule:
        current = self.schedules.get(schedule.schedule_id)
        if current is None or current.schedule_version != expected_version:
            raise TaskScheduleConflictError
        self.schedules[schedule.schedule_id] = schedule
        return schedule

    def replace_authority(
        self,
        schedule: TaskSchedule,
        authority: ScheduleAuthorityBinding,
        previous_authority: ScheduleAuthorityBinding,
        *,
        expected_version: int,
        expected_authority_revision: int,
    ) -> TaskSchedule:
        current = self.authorities.get(schedule.schedule_id)
        if (
            current is None
            or current.binding_revision != expected_authority_revision
            or self.schedules[schedule.schedule_id].schedule_version != expected_version
        ):
            raise TaskScheduleConflictError
        self.schedules[schedule.schedule_id] = schedule
        self.authorities[schedule.schedule_id] = authority
        assert previous_authority.revoked_at is not None
        return schedule


class MemoryFiringStore:
    deployment_namespace = "cloud"

    def __init__(self) -> None:
        self.firings: dict[TaskScheduleFiringId, TaskScheduleFiring] = {}

    def create_manual(
        self,
        schedule: TaskSchedule,
        *,
        owner: ScheduleOwner,
        idempotency_key: str,
    ) -> TaskScheduleFiring:
        assert schedule.owner == owner
        fire_id = manual_task_schedule_firing_id(schedule.schedule_id, idempotency_key)
        existing = self.firings.get(fire_id)
        if existing is not None:
            return existing
        now = datetime.now(UTC)
        firing = TaskScheduleFiring(
            fire_id=fire_id,
            schedule_id=schedule.schedule_id,
            schedule_version=schedule.schedule_version,
            schedule_snapshot=schedule,
            scheduled_for=now,
            status=ScheduleFiringStatus.MATERIALIZING,
            attempt=0,
            claimed_by="schedule-api-run-now",
            claim_expires_at=now + timedelta(milliseconds=1),
            created_at=now,
        )
        self.firings[fire_id] = firing
        return firing

    def list_for_schedule(
        self, schedule_id: TaskScheduleId, *, owner: ScheduleOwner, limit: int
    ) -> tuple[TaskScheduleFiring, ...]:
        values = (
            item
            for item in self.firings.values()
            if item.schedule_id == schedule_id and item.schedule_snapshot.owner == owner
        )
        return tuple(values)[:limit]

    def get_for_owner(
        self,
        fire_id: TaskScheduleFiringId,
        *,
        schedule_id: TaskScheduleId,
        owner: ScheduleOwner,
    ) -> TaskScheduleFiring | None:
        firing = self.firings.get(fire_id)
        if (
            firing is None
            or firing.schedule_id != schedule_id
            or firing.schedule_snapshot.owner != owner
        ):
            return None
        return firing

    def claim_due(
        self, *, claimant: str, limit: int, claim_ttl_seconds: int
    ) -> tuple[TaskScheduleFiring, ...]:
        return ()

    def get_firing(self, fire_id: TaskScheduleFiringId) -> TaskScheduleFiring | None:
        return self.firings.get(fire_id)

    def settle_firing(
        self,
        firing: TaskScheduleFiring,
        *,
        expected_status: ScheduleFiringStatus,
        expected_claim_expiry: datetime | None,
    ) -> TaskScheduleFiring:
        self.firings[firing.fire_id] = firing
        return firing


def _verified(
    *, principal: str = "user-1", scopes: tuple[str, ...] | None = None
) -> VerifiedHostGrant:
    context = HostContextEnvelope(
        grant_id=f"grant-{principal}",
        host_app_id="trench",
        namespace_id="tenant-1",
        workspace_ref="workspace-1",
        resource_refs=({"type": "principal", "id": principal},),
        scopes=scopes or ("agent.run", "schedule.read", "schedule.manage"),
        limits={
            "max_runtime_seconds": 1_800,
            "max_model_tokens": 1_000_000,
            "max_artifact_bytes": 64_000_000,
        },
        origin="https://trench.example",
        policy_version="trench-v1",
    )
    return VerifiedHostGrant(
        context=context,
        grant_id=context.grant_id,
        algorithm=JwtAlgorithm.RS256,
        authority_issuer="https://trench.example",
        subject_ref=principal,
    )


def _request(
    method: str,
    path: str,
    *,
    verified: VerifiedHostGrant,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
) -> RouteRequest:
    return RouteRequest(
        method,
        path,
        body=body,
        headers=headers,
        query=query,
        host_context=verified.context,
        verified_host_grant=verified,
    )


def _adapter(tmp_path: Path) -> RouteAdapter:
    schedules = MemoryScheduleStore()
    firings = MemoryFiringStore()
    return RouteAdapter(
        create_app(
            tmp_path / "schedule-api.sqlite",
            task_schedule_store=schedules,
            task_schedule_firing_store=firings,
        )
    )


def test_schedule_management_lifecycle_is_scoped_versioned_and_run_now_idempotent(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    verified = _verified()
    created = adapter.handle(
        _request(
            "POST",
            "/schedules",
            verified=verified,
            body={
                "title": "Daily market report",
                "timezone": "Asia/Shanghai",
                "trigger": {"kind": "daily", "local_time": "09:00"},
                "task_template": {
                    "title": "Market report",
                    "prompt": "Summarize today's market news",
                    "workspace": ".",
                },
            },
        )
    )
    assert created.status_code == 201
    schedule_id = str(created.body["schedule_id"])
    assert created.body["schedule_version"] == 1
    assert created.body["task_template"] == {
        "prompt": "Summarize today's market news",
        "title": "Market report",
        "workspace": ".",
    }

    listed = adapter.handle(_request("GET", "/schedules", verified=verified))
    assert listed.status_code == 200
    assert listed.body["count"] == 1
    denied = adapter.handle(
        _request("GET", f"/schedules/{schedule_id}", verified=_verified(principal="user-2"))
    )
    assert denied.status_code == 404

    patched = adapter.handle(
        _request(
            "PATCH",
            f"/schedules/{schedule_id}",
            verified=verified,
            body={
                "title": "Morning market report",
                "task_template": {
                    "title": "Updated market report",
                    "prompt": "Summarize market news and identify risks",
                    "workspace": ".",
                },
            },
            headers={"If-Match": '"1"'},
        )
    )
    assert patched.status_code == 200
    assert patched.body["schedule_version"] == 2
    assert patched.body["task_template"]["prompt"] == ("Summarize market news and identify risks")
    conflict = adapter.handle(
        _request(
            "POST",
            f"/schedules/{schedule_id}/pause",
            verified=verified,
            body={"schedule_version": 1},
        )
    )
    assert conflict.status_code == 409

    paused = adapter.handle(
        _request(
            "POST",
            f"/schedules/{schedule_id}/pause",
            verified=verified,
            body={"schedule_version": 2},
        )
    )
    assert paused.body["status"] == "paused"
    resumed = adapter.handle(
        _request(
            "POST",
            f"/schedules/{schedule_id}/resume",
            verified=verified,
            body={"schedule_version": 3},
        )
    )
    assert resumed.body["status"] == "active"

    run_request = _request(
        "POST",
        f"/schedules/{schedule_id}/run-now",
        verified=verified,
        headers={"Idempotency-Key": "run-1"},
    )
    first_run = adapter.handle(run_request)
    replayed_run = adapter.handle(run_request)
    assert first_run.status_code == replayed_run.status_code == 202
    assert first_run.body["fire_id"] == replayed_run.body["fire_id"]
    runs = adapter.handle(_request("GET", f"/schedules/{schedule_id}/runs", verified=verified))
    assert runs.body["count"] == 1
    run = adapter.handle(
        _request(
            "GET",
            f"/schedules/{schedule_id}/runs/{first_run.body['fire_id']}",
            verified=verified,
        )
    )
    assert run.status_code == 200

    deleted = adapter.handle(
        _request(
            "DELETE",
            f"/schedules/{schedule_id}",
            verified=verified,
            body={"schedule_version": 4},
        )
    )
    assert deleted.body["status"] == "deleted"
    assert (
        adapter.handle(_request("GET", f"/schedules/{schedule_id}", verified=verified)).status_code
        == 404
    )
    assert adapter.handle(_request("GET", "/schedules", verified=verified)).body["count"] == 0
    assert (
        adapter.handle(
            _request("GET", "/schedules", verified=verified, query={"include_deleted": "true"})
        ).body["count"]
        == 1
    )


def test_schedule_management_requires_verified_scoped_grant(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    missing_scope = _verified(scopes=("agent.run", "schedule.read"))

    response = adapter.handle(
        _request(
            "POST",
            "/schedules",
            verified=missing_scope,
            body={},
        )
    )

    assert response.status_code == 403
    assert response.body["reason"] == "schedule.manage scope is required"


def test_http_schedule_routes_select_read_and_manage_scopes() -> None:
    def request(method: str) -> HostGrantHttpRequest:
        return HostGrantHttpRequest(method, "/schedules", None, "Bearer token")

    assert _required_scopes_for_request(request("GET")) == ("schedule.read",)
    assert _required_scopes_for_request(request("POST")) == (
        "agent.run",
        "schedule.manage",
    )
