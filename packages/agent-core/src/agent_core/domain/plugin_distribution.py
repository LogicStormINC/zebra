"""Exact product grant to a trusted business identity; never a HostGrant."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.runtime_bundle_types import BundleScope, BundleValue, Digest


class PluginDistributionCommand(BundleValue):
    action: Literal["distribute", "withdraw"]
    scope: BundleScope
    recipient: ExtensionScope
    package_digest: Digest
    publication_operation: Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]
    operation_id: Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]
    expected_revision: Annotated[int, Field(ge=0, le=2**53 - 2)]

    @model_validator(mode="after")
    def exact(self) -> Self:
        if any(str(UUID(v)) != v for v in (self.operation_id, self.publication_operation)):
            raise ValueError("INVALID_OPERATION")
        if (self.recipient.authority_issuer, self.recipient.namespace_id) != (
            self.scope.authority_issuer,
            self.scope.namespace_id,
        ):
            raise ValueError("RECIPIENT_SCOPE_MISMATCH")
        if (
            self.operation_id == self.publication_operation
            or self.action == "withdraw"
            and self.expected_revision == 0
        ):
            raise ValueError("INVALID_DISTRIBUTION")
        return self
