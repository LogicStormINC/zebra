"""Separate product publisher authority; never a business user or HostGrant."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from agent_core.domain.runtime_bundle_json import json_digest, load_bundle_json
from agent_core.domain.runtime_bundle_types import Digest
from agent_storage.postgres.host_management import HostManagementTrust
from pydantic import BeforeValidator, Field, model_validator
from zebra_agent_config.private_configuration import read_private_configuration

from zebra_agent_api.script_validation_config import ScriptValidationApproval


class PluginAdmissionApproval(ScriptValidationApproval):
    schema_version: Literal["cloud-agent.plugin-admission-approval/1"]  # type: ignore[assignment]
    actions: Annotated[  # type: ignore[assignment]
        tuple[
            Literal["plugin.contract.read", "plugin.validate", "plugin.publish", "plugin.read"], ...
        ],
        BeforeValidator(lambda v: tuple(v) if type(v) is list else v),
        Field(min_length=1, max_length=4),
    ]
    package_digests: Annotated[
        tuple[Digest, ...],
        BeforeValidator(lambda v: tuple(v) if type(v) is list else v),
        Field(max_length=128),
    ]

    @model_validator(mode="after")
    def unique_digests(self) -> Self:
        if len(set(self.package_digests)) != len(self.package_digests):
            raise ValueError("INVALID_PLUGIN_APPROVAL")
        return self

    @property
    def actor(self) -> str:
        # One shared authority per full product target scope, including replicas.
        # Changing credentials cannot create a second live catalog for that scope.
        return "plugin-" + json_digest(self.scope.model_dump(mode="json"))[7:]

    @property
    def trust(self) -> HostManagementTrust:
        return HostManagementTrust(
            self.scope.deployment_id,
            self.audience,
            self.scope.product_id,
            self.scope.environment,
            self.actor,
            self.scope.namespace_id,
            self.trust_revision,
            json_digest(self.model_dump(mode="json"))[7:],
            datetime.fromisoformat(self.expires_at),
        )


def load_plugin_approval(path: str | None, namespace: str | None) -> PluginAdmissionApproval:
    if path is None or not Path(path).is_absolute():
        raise ValueError("PRIVATE_CONFIGURATION_REQUIRED")
    approval = PluginAdmissionApproval.model_validate(
        load_bundle_json(read_private_configuration(path, max_bytes=32768))
    )
    if namespace is None or approval.scope.namespace_id != namespace:
        raise ValueError("NAMESPACE_MISMATCH")
    # Validate the shared-store limits before any mutation.
    _ = approval.trust
    return approval
