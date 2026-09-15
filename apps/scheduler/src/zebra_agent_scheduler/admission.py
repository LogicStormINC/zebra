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
from zebra_agent_api.agent_definition_binding import resolve_definition_binding
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.extension_task_selection import validate_task_skill_selection
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_binding import NO_CONNECTOR_DIGEST
from zebra_agent_api.session_payloads import parse_create_session_payload


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
        payload = {**template.payload, "execute": True}
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
        return self._task_id(response)

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
