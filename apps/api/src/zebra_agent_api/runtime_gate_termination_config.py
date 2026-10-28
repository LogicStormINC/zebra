"""Opt-in original termination authority, separate from gate and business credentials."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from agent_core.domain.runtime_bundle_json import json_digest, load_bundle_json
from agent_core.domain.runtime_bundle_types import BundleScope, BundleValue
from agent_core.domain.runtime_gate_termination import CONTRACT_DIGEST
from agent_storage.postgres.host_management import HostManagementTrust
from pydantic import BeforeValidator, Field, model_validator
from zebra_agent_config.private_configuration import read_private_configuration


class RuntimeGateTerminationApproval(BundleValue):
    schema_version: Literal["cloud-agent.runtime-gate-termination-approval/1"]
    scope: BundleScope
    audience: Annotated[str, Field(min_length=1, max_length=128)]
    actor: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,115}$")]
    namespace_exclusive: Annotated[bool, Field(strict=True)]
    contract_digest: str
    trust_revision: Annotated[int, Field(strict=True, ge=1, lt=2**53)]
    credential_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", repr=False)]
    expires_at: Annotated[
        datetime, BeforeValidator(lambda v: datetime.fromisoformat(v) if isinstance(v, str) else v)
    ]
    actions: Annotated[
        tuple[Literal["read", "terminate"], ...],
        BeforeValidator(lambda v: tuple(v) if isinstance(v, list) else v),
        Field(min_length=1, max_length=2),
    ]

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if (
            not self.namespace_exclusive
            or self.contract_digest != CONTRACT_DIGEST
            or self.expires_at.tzinfo is None
            or len(set(self.actions)) != len(self.actions)
            or (set(self.actions) - {"read"} and "read" not in self.actions)
        ):
            raise ValueError("INVALID_GATE_APPROVAL")
        return self

    @property
    def trust(self) -> HostManagementTrust:
        return HostManagementTrust(
            self.scope.deployment_id,
            self.audience,
            self.scope.product_id,
            self.scope.environment,
            "gate-stop-" + self.actor,
            self.scope.namespace_id,
            self.trust_revision,
            json_digest(self.model_dump(mode="json")).removeprefix("sha256:"),
            self.expires_at,
        )


def load_runtime_gate_termination_approval(
    path: str | None, namespace: str | None
) -> RuntimeGateTerminationApproval:
    if path is None or not Path(path).is_absolute():
        raise ValueError("GATE_CONFIGURATION_REQUIRED")
    value = RuntimeGateTerminationApproval.model_validate(
        load_bundle_json(read_private_configuration(path, max_bytes=16384))
    )
    if value.scope.namespace_id != namespace or value.expires_at <= datetime.now(UTC):
        raise ValueError("GATE_APPROVAL_UNAVAILABLE")
    return value
