"""Signed workload exchange for fresh, schedule-scoped Host authority."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from agent_core.application.task_schedule_materializer import ScheduleAuthorityRejected
from agent_core.domain.host_authority import HostContextEnvelope, HostTechnicalLimits
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduleExecutionAuthority,
)
from agent_core.domain.task_schedules import TaskScheduleFiring
from agent_security import HostGrantVerificationConfig, HostGrantVerifier, PyJwtHostGrantDecoder

_NON_RUNTIME_SCOPES = frozenset({"schedule.read", "schedule.manage", "extensions.manage"})


@dataclass(frozen=True)
class ScheduleGrantExchangeSettings:
    exchange_url: str
    workload_identity: str
    workload_shared_secret: str = field(repr=False)
    verification: HostGrantVerificationConfig
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.exchange_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("schedule grant exchange_url must be HTTPS without credentials")
        if not self.workload_identity.strip() or len(self.workload_identity) > 128:
            raise ValueError("schedule workload identity must be non-blank and bounded")
        if not self.workload_shared_secret:
            raise ValueError("schedule workload shared secret is required")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("schedule exchange timeout must be between 0 and 30 seconds")


@dataclass(frozen=True)
class HttpScheduleAuthorityRevalidator:
    settings: ScheduleGrantExchangeSettings
    decoder: PyJwtHostGrantDecoder
    client: httpx.Client | None = field(default=None, repr=False)
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def revalidate(
        self,
        binding: ScheduleAuthorityBinding,
        firing: TaskScheduleFiring,
    ) -> ScheduleExecutionAuthority:
        body = self._body(binding, firing)
        moment = self.now().astimezone(UTC)
        timestamp = str(int(moment.timestamp()))
        nonce = str(firing.fire_id)
        headers = {
            "X-Zebra-Workload-Identity": self.settings.workload_identity,
            "X-Zebra-Workload-Timestamp": timestamp,
            "X-Zebra-Workload-Nonce": nonce,
            "X-Zebra-Workload-Signature": self._signature(body, timestamp, nonce),
        }
        try:
            if self.client is None:
                response = httpx.post(
                    self.settings.exchange_url,
                    json=body,
                    headers=headers,
                    timeout=self.settings.timeout_seconds,
                )
            else:
                response = self.client.post(
                    self.settings.exchange_url,
                    json=body,
                    headers=headers,
                    timeout=self.settings.timeout_seconds,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("schedule Host authority exchange is unavailable") from exc
        if response.status_code >= 500:
            raise RuntimeError("schedule Host authority exchange is unavailable")
        if response.status_code != 200:
            raise ScheduleAuthorityRejected("host_exchange_rejected")
        token = response.json().get("grant")
        if not isinstance(token, str):
            raise ScheduleAuthorityRejected("host_exchange_invalid")
        try:
            decoded = self.decoder.decode(token, config=self.settings.verification)
            verified = HostGrantVerifier(self.settings.verification).verify(
                decoded.grant,
                algorithm=decoded.algorithm,
                now=moment,
                expected_host_app_id=binding.owner.host_app_id,
                required_scopes=self._runtime_scopes(binding),
            )
            narrowed = self._narrow(binding, firing, verified.context)
        except ScheduleAuthorityRejected:
            raise
        except Exception as exc:
            raise ScheduleAuthorityRejected("fresh_host_authority_invalid") from exc
        return ScheduleExecutionAuthority(
            host_context=narrowed,
            authority_issuer=verified.authority_issuer,
            grant_id=verified.grant_id,
            subject_ref=verified.subject_ref,
            algorithm=verified.algorithm.value,
        )

    def _body(
        self, binding: ScheduleAuthorityBinding, firing: TaskScheduleFiring
    ) -> dict[str, object]:
        original = binding.host_context
        resources = [
            {"type": ref.resource_type, "id": ref.resource_id}
            for ref in original.resource_refs
            if ref.resource_type.startswith("trench.")
        ]
        return {
            "audience": self.settings.verification.audience,
            "threadId": str(firing.schedule_id),
            "runId": str(firing.fire_id),
            "scopes": list(self._runtime_scopes(binding)),
            "resourceRefs": resources,
            "principal": {
                "userId": binding.owner.principal_id,
                "workspaceId": binding.owner.workspace_id,
                "activeSourceIds": [
                    ref.resource_id
                    for ref in original.resource_refs
                    if ref.resource_type == "trench.source"
                ],
                "agentScopes": list(original.scopes),
            },
        }

    def _narrow(
        self,
        binding: ScheduleAuthorityBinding,
        firing: TaskScheduleFiring,
        fresh: HostContextEnvelope,
    ) -> HostContextEnvelope:
        original = binding.host_context
        if (
            fresh.namespace_id != binding.owner.tenant_id
            or fresh.workspace_ref != binding.owner.workspace_id
            or fresh.host_app_id != binding.owner.host_app_id
            or fresh.origin != original.origin
            or fresh.policy_version != original.policy_version
        ):
            raise ScheduleAuthorityRejected("host_identity_drifted")
        principals = tuple(
            ref.resource_id for ref in fresh.resource_refs if ref.resource_type == "principal"
        )
        if principals != (binding.owner.principal_id,):
            raise ScheduleAuthorityRejected("principal_drifted")
        required = {
            (ref.resource_type, ref.resource_id)
            for ref in original.resource_refs
            if ref.resource_type.startswith("trench.")
        }
        actual = {(ref.resource_type, ref.resource_id) for ref in fresh.resource_refs}
        if not required <= actual:
            raise ScheduleAuthorityRejected("resource_authority_drifted")
        limits = HostTechnicalLimits(
            max_runtime_seconds=min(
                fresh.limits.max_runtime_seconds, original.limits.max_runtime_seconds
            ),
            max_model_tokens=min(fresh.limits.max_model_tokens, original.limits.max_model_tokens),
            max_artifact_bytes=min(
                fresh.limits.max_artifact_bytes, original.limits.max_artifact_bytes
            ),
        )
        return fresh.model_copy(
            update={
                "scopes": self._runtime_scopes(binding),
                "limits": limits,
                "resource_refs": tuple(
                    ref
                    for ref in fresh.resource_refs
                    if ref.resource_type in {"thread", "run", "principal"}
                    or ref.resource_type.startswith("trench.")
                ),
            }
        )

    @staticmethod
    def _runtime_scopes(binding: ScheduleAuthorityBinding) -> tuple[str, ...]:
        return tuple(
            scope for scope in binding.host_context.scopes if scope not in _NON_RUNTIME_SCOPES
        )

    def _signature(self, body: dict[str, object], timestamp: str, nonce: str) -> str:
        canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        signed = f"{timestamp}\n{nonce}\n{digest}".encode()
        return hmac.new(
            self.settings.workload_shared_secret.encode(), signed, hashlib.sha256
        ).hexdigest()
