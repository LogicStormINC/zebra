"""Reuse the normal Zebra API Task admission seam for scheduled Firings."""

from __future__ import annotations

from typing import Never
from uuid import UUID

from agent_core.application import ScheduleAuthorityRejected
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduledTaskTemplate,
    ScheduleExecutionAuthority,
)
from agent_core.domain.task_schedules import TaskScheduleFiring
from agent_security import JwtAlgorithm, VerifiedHostGrant
from zebra_agent_api.ag_ui_command import handle_agui_command
from zebra_agent_api.agent_definition_binding import resolve_definition_binding
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.extension_task_selection import validate_task_skill_selection
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteRequest
from zebra_agent_api.session_binding import NO_CONNECTOR_DIGEST
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.task_schedule_template import split_schedule_template


class ZebraApiScheduledTaskAdmission:
    def __init__(
        self,
        api: ZebraAgentApi,
        *,
        extension_admission: CloudExtensionTurnAdmission | None = None,
    ) -> None:
        self.api = api
        self.extension_admission = extension_admission

    def admit(
        self,
        template: ScheduledTaskTemplate,
        *,
        binding: ScheduleAuthorityBinding,
        firing: TaskScheduleFiring,
        execution_authority: ScheduleExecutionAuthority,
        idempotency_key: str,
    ) -> TaskId:
        try:
            prepared, selection, stream = split_schedule_template(template.payload)
        except ValueError as exc:
            raise ScheduleAuthorityRejected("scheduled_command_invalid") from exc
        payload = {**prepared, "execute": False}
        verified = VerifiedHostGrant(
            context=execution_authority.host_context,
            grant_id=execution_authority.grant_id,
            algorithm=JwtAlgorithm(execution_authority.algorithm),
            authority_issuer=execution_authority.authority_issuer,
            subject_ref=execution_authority.subject_ref,
        )
        self._validate_frozen_admission(payload, binding, verified)
        response = self.api.create_session(
            payload,
            idempotency_key=idempotency_key,
            host_context=execution_authority.host_context,
            verified_host_grant=verified,
        )
        task_id = self._task_id(response)
        revision = response.body.get("current_sequence")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise RuntimeError("scheduled Task admission returned no revision")
        if selection is not None or stream is not None:
            run_id = str(firing.fire_id)
            command = handle_agui_command(
                self.api,
                RouteRequest(
                    "POST",
                    "/agui/commands",
                    verified_host_grant=verified,
                    host_context=verified.context,
                    headers={"Idempotency-Key": f"schedule:{firing.fire_id}:run"},
                    body={
                        "action": "run",
                        "threadId": str(task_id),
                        "runId": run_id,
                        "expectedRevision": revision,
                        **(
                            {"extensionSelection": selection.model_dump(mode="json")}
                            if selection
                            else {}
                        ),
                        **(
                            {"streamCapabilities": stream.model_dump(mode="json")} if stream else {}
                        ),
                        "input": {
                            "threadId": str(task_id),
                            "runId": run_id,
                            "messages": [],
                            "tools": [],
                            "context": [],
                            "state": {},
                            "forwardedProps": {},
                        },
                    },
                ),
                extension_admission=self.extension_admission,
            )
        else:
            command = self.api.submit_command(
                str(task_id),
                {
                    "kind": "run",
                    "expected_revision": revision,
                    "payload": {"run_id": f"schedule:{firing.fire_id}:run"},
                },
                idempotency_key=f"schedule:{firing.fire_id}:run",
                extension_admission=self.extension_admission,
                verified_host_grant=verified,
            )
        if command is None:
            raise ScheduleAuthorityRejected("agui_admission_unavailable")
        status = command.body.get("status")
        if (
            command.status_code not in {200, 202}
            or not isinstance(status, str)
            or status
            not in {
                "accepted",
                "duplicate",
            }
        ):
            self._reject_or_retry(command, "task_command")
        return task_id

    def _validate_frozen_admission(
        self,
        payload: dict[str, object],
        binding: ScheduleAuthorityBinding,
        verified: VerifiedHostGrant,
    ) -> None:
        parsed = parse_create_session_payload(payload)
        if isinstance(parsed, ApiResponse):
            raise ScheduleAuthorityRejected("task_template_invalid")
        skill_error = validate_task_skill_selection(payload, verified, self.extension_admission)
        if skill_error is not None:
            self._reject_or_retry(skill_error, "skill_selection")
        definition = resolve_definition_binding(
            self.api.agent_registry,
            self.api.publisher_grants,
            parsed,
            host_context=verified.context,
        )
        if isinstance(definition, ApiResponse):
            self._reject_or_retry(definition, "definition_binding")
        digest = definition.definition_digest if definition is not None else NO_CONNECTOR_DIGEST
        if digest != binding.agent_definition_digest:
            raise ScheduleAuthorityRejected("agent_definition_drifted")

    @staticmethod
    def _task_id(response: ApiResponse) -> TaskId:
        if response.status_code != 201:
            ZebraApiScheduledTaskAdmission._reject_or_retry(response, "task_admission")
        raw = response.body.get("session_id")
        try:
            return TaskId(UUID(str(raw)))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("scheduled Task admission returned no Task id") from exc

    @staticmethod
    def _reject_or_retry(response: ApiResponse, prefix: str) -> Never:
        if response.status_code >= 500:
            raise RuntimeError(f"{prefix} is temporarily unavailable")
        status = response.body.get("status")
        suffix = status if isinstance(status, str) and status.strip() else "rejected"
        raise ScheduleAuthorityRejected(f"{prefix}_{suffix}")
