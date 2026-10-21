"""Explicit, separate private authority for pure Bundle queries."""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.domain.runtime_bundle_types import BundleScope, BundleValue, Identifier
from pydantic import BeforeValidator, Field, model_validator
from zebra_agent_config.private_configuration import read_private_configuration

Action = Literal["bundle.contract.read", "bundle.validate"]


class BundleManagementApproval(BundleValue):
    schema_version: Literal["cloud-agent.bundle-management-approval/1"]
    scope: BundleScope
    audience: Identifier
    trust_revision: Annotated[int, Field(ge=1, le=2**53 - 1)]
    credential_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", repr=False)]
    expires_at: str
    actions: Annotated[
        tuple[Action, ...],
        BeforeValidator(lambda value: tuple(value) if type(value) is list else value),
        Field(min_length=1, max_length=2),
    ]

    @model_validator(mode="after")
    def valid_deadline_and_actions(self) -> Self:
        if (
            re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", self.expires_at)
            is None
            or self.deadline.utcoffset() != UTC.utcoffset(None)
            or len(set(self.actions)) != len(self.actions)
        ):
            raise ValueError("INVALID_APPROVAL")
        return self

    @property
    def deadline(self) -> datetime:
        return datetime.fromisoformat(self.expires_at)


def load_bundle_management_approval(
    path: str | None, namespace: str | None
) -> BundleManagementApproval:
    try:
        if path is None or not Path(path).is_absolute():
            raise ValueError("PRIVATE_CONFIGURATION_REQUIRED")
        raw = read_private_configuration(path, max_bytes=16_384)
        approval = BundleManagementApproval.model_validate(load_bundle_json(raw))
        if namespace is None or approval.scope.namespace_id != namespace:
            raise ValueError("NAMESPACE_MISMATCH")
        return approval
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("INVALID_BUNDLE_MANAGEMENT_APPROVAL") from None
