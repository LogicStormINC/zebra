"""Private, exact publisher ceilings. No business HostGrant privileges."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from agent_core.application.agent_definitions import (
    PublisherGrantCeiling,
    StaticPublisherGrantResolver,
)
from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_core.domain.identifiers import AgentDefinitionId
from agent_core.domain.runtime_bundle_json import json_digest, load_bundle_json
from agent_core.domain.runtime_bundle_types import BundleScope, BundleValue, Identifier
from agent_storage.postgres.host_management import HostManagementTrust
from pydantic import BeforeValidator, Field
from zebra_agent_config.private_configuration import read_private_configuration


class PublicationApproval(BundleValue):
    schema_version: Literal["cloud-agent.publication-approval/1"]
    scope: BundleScope
    audience: Identifier
    actor: Identifier
    definition_id: Annotated[UUID, BeforeValidator(lambda v: UUID(v) if isinstance(v, str) else v)]
    trust_revision: Annotated[int, Field(ge=1, le=2**53 - 1)]
    credential_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", repr=False)]
    expires_at: str
    actions: Annotated[
        tuple[Literal["materialize", "publish", "read"], ...],
        BeforeValidator(lambda value: tuple(value) if type(value) is list else value),
        Field(min_length=1, max_length=3),
    ]
    references: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=512)], ...],
        BeforeValidator(lambda value: tuple(value) if type(value) is list else value),
        Field(min_length=1, max_length=128),
    ]
    template: dict[str, str]
    evaluator_actors: Annotated[
        tuple[Identifier, ...],
        BeforeValidator(lambda value: tuple(value) if type(value) is list else value),
        Field(min_length=1, max_length=16),
    ]
    consumer_hosts: Annotated[
        tuple[Identifier, ...],
        BeforeValidator(lambda value: tuple(value) if type(value) is list else value),
        Field(max_length=32),
    ] = ()
    policy_version: Identifier

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
            json_digest(self.model_dump(mode="json")).removeprefix("sha256:"),
            datetime.fromisoformat(self.expires_at),
        )

    @property
    def definition_scope(self) -> AgentDefinitionScope:
        return AgentDefinitionScope(
            authority_issuer=self.scope.authority_issuer,
            namespace_id=self.scope.namespace_id,
            definition_id=AgentDefinitionId(self.definition_id),
        )

    def resolver(self) -> StaticPublisherGrantResolver:
        return StaticPublisherGrantResolver(
            {
                f"{self.actor}@{self.scope.namespace_id}": PublisherGrantCeiling(
                    self.scope.authority_issuer, self.scope.namespace_id, frozenset(self.references)
                )
            }
        )


def load_publication_approval(path: str | None, namespace: str | None) -> PublicationApproval:
    if path is None or not Path(path).is_absolute():
        raise ValueError("PRIVATE_CONFIGURATION_REQUIRED")
    value = load_bundle_json(read_private_configuration(path, max_bytes=32768))
    approval = PublicationApproval.model_validate(value)
    required = {
        "name",
        "description",
        "model_policy_ref",
        "tool_profile_ref",
        "skill_snapshot_digest",
        "memory_policy_ref",
        "security_policy_ref",
        "evaluation_profile_ref",
        "runtime_profile_ref",
    }
    if (
        approval.scope.namespace_id != namespace
        or set(approval.template) != required
        or len(set(approval.actions)) != len(approval.actions)
        or len(set(approval.references)) != len(approval.references)
        or any("*" in ref for ref in approval.references)
        or approval.trust.expires_at.tzinfo is None
        or approval.trust.expires_at <= datetime.now(UTC)
    ):
        raise ValueError("INVALID_PUBLICATION_APPROVAL")
    return approval
