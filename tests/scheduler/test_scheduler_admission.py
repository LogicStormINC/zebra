from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from agent_core.application import ScheduleAuthorityRejected
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskScheduleId
from agent_core.domain.task_bindings import host_context_digest
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduledTaskTemplate,
    ScheduleExecutionAuthority,
    ScheduleOwner,
)
from agent_core.domain.task_schedules import (
    DailyScheduleTrigger,
    TaskSchedule,
    TaskScheduleFiring,
)
from zebra_agent_api import ApiResponse, ZebraAgentApi
from zebra_agent_scheduler import ZebraApiScheduledTaskAdmission

NOW = datetime(2026, 9, 15, 4, tzinfo=UTC)


def host_context(*, grant_id: str) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id=grant_id,
        host_app_id="trench",
        namespace_id="tenant-1",
        workspace_ref="workspace-1",
        resource_refs=({"type": "principal", "id": "user-1"},),
        scopes=("agent.run", "schedule.manage"),
        limits={
            "max_runtime_seconds": 1800,
            "max_model_tokens": 1_000_000,
            "max_artifact_bytes": 64_000_000,
        },
        origin="https://trench.example",
        policy_version="policy-v1",
    )


def schedule_fixture() -> tuple[TaskScheduleFiring, ScheduleAuthorityBinding]:
    schedule_id = TaskScheduleId(uuid4())
    binding_id = uuid4()
    owner = ScheduleOwner(
        deployment_namespace="cloud",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id="user-1",
        host_app_id="trench",
    )
    template = ScheduledTaskTemplate(payload={"prompt": "Daily report", "title": "Report"})
    schedule = TaskSchedule(
        schedule_id=schedule_id,
        owner=owner,
        title="Daily report",
        timezone="Asia/Shanghai",
        trigger=DailyScheduleTrigger(local_time=time(9)),
        task_template=template,
        authority_binding_id=binding_id,
        schedule_version=1,
        next_fire_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    original = host_context(grant_id="login-grant")
    binding = ScheduleAuthorityBinding(
        binding_id=binding_id,
        schedule_id=schedule_id,
        owner=owner,
        host_context=original,
        host_capability_digest=host_context_digest(original),
        agent_definition_digest="0" * 64,
        policy_digest="b" * 64,
        extension_snapshot_digest="c" * 64,
        binding_revision=1,
        bound_at=NOW,
    )
    firing = TaskScheduleFiring(
        fire_id=uuid4(),
        schedule_id=schedule_id,
        schedule_version=1,
        schedule_snapshot=schedule,
        scheduled_for=NOW,
        attempt=1,
        claimed_by="scheduler",
        claim_expires_at=NOW.replace(minute=1),
        created_at=NOW,
    )
    return firing, binding


class FakeApi:
    agent_registry = None
    publisher_grants = None

    def __init__(self, response: ApiResponse, command: ApiResponse | None = None) -> None:
        self.response = response
        self.command = command or ApiResponse(202, {"status": "accepted"})
        self.calls: list[dict[str, object]] = []

    def create_session(self, payload: dict[str, object], **kwargs: object) -> ApiResponse:
        self.calls.append({"payload": payload, **kwargs})
        return self.response

    def submit_command(
        self, session_id: str, payload: dict[str, object], **kwargs: object
    ) -> ApiResponse:
        self.calls.append({"session_id": session_id, "payload": payload, **kwargs})
        return self.command


def execution(binding: ScheduleAuthorityBinding) -> ScheduleExecutionAuthority:
    fresh = host_context(grant_id="fresh-grant")
    return ScheduleExecutionAuthority(
        host_context=fresh,
        authority_issuer="https://broker.example",
        grant_id="fresh-grant",
        subject_ref=binding.owner.principal_id,
        algorithm="RS256",
    )


def test_scheduled_admission_reuses_api_queue_with_stable_key() -> None:
    task_id = uuid4()
    api = FakeApi(
        ApiResponse(
            201,
            {"session_id": str(task_id), "status": "awaiting_input", "current_sequence": 2},
        )
    )
    firing, binding = schedule_fixture()
    admission = ZebraApiScheduledTaskAdmission(cast(ZebraAgentApi, cast(Any, api)))

    admitted = admission.admit(
        firing.schedule_snapshot.task_template,
        binding=binding,
        firing=firing,
        execution_authority=execution(binding),
        idempotency_key=firing.idempotency_key,
    )

    assert UUID(str(admitted)) == task_id
    assert api.calls[0]["idempotency_key"] == firing.idempotency_key
    assert cast(dict[str, object], api.calls[0]["payload"])["execute"] is False
    assert api.calls[1]["session_id"] == str(task_id)
    assert api.calls[1]["payload"] == {"kind": "run", "expected_revision": 2}
    assert api.calls[1]["idempotency_key"] == f"schedule:{firing.fire_id}:run"
    assert api.calls[1]["verified_host_grant"].grant_id == "fresh-grant"


def test_scheduled_admission_classifies_permanent_and_transient_failures() -> None:
    firing, binding = schedule_fixture()
    permanent = FakeApi(ApiResponse(400, {"status": "invalid_request"}))
    admission = ZebraApiScheduledTaskAdmission(cast(ZebraAgentApi, cast(Any, permanent)))
    with pytest.raises(ScheduleAuthorityRejected, match="task_admission_invalid_request"):
        admission.admit(
            firing.schedule_snapshot.task_template,
            binding=binding,
            firing=firing,
            execution_authority=execution(binding),
            idempotency_key=firing.idempotency_key,
        )

    transient = FakeApi(ApiResponse(503, {"status": "unavailable"}))
    admission = ZebraApiScheduledTaskAdmission(cast(ZebraAgentApi, cast(Any, transient)))
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        admission.admit(
            firing.schedule_snapshot.task_template,
            binding=binding,
            firing=firing,
            execution_authority=execution(binding),
            idempotency_key=firing.idempotency_key,
        )


def test_scheduled_admission_classifies_command_failure() -> None:
    task_id = uuid4()
    firing, binding = schedule_fixture()
    api = FakeApi(
        ApiResponse(201, {"session_id": str(task_id), "current_sequence": 2}),
        ApiResponse(503, {"status": "extension_admission_unavailable"}),
    )
    admission = ZebraApiScheduledTaskAdmission(cast(ZebraAgentApi, cast(Any, api)))

    with pytest.raises(RuntimeError, match="task_command is temporarily unavailable"):
        admission.admit(
            firing.schedule_snapshot.task_template,
            binding=binding,
            firing=firing,
            execution_authority=execution(binding),
            idempotency_key=firing.idempotency_key,
        )
