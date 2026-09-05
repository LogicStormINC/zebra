"""Strict sanitized delivery diagnosis, deliberately not a business envelope."""

import json
from typing import Annotated, Literal

from pydantic import Field

from .broker_envelope import CanonicalUUID, FrozenModel, Namespace, _unique_object

ConsumerRole = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9_.-]{0,95}$")]
RejectionCode = Literal["invalid_broker_envelope", "broker_hint_conflict"]


class BrokerDiagnostic(FrozenModel):
    message_type: Literal["broker.delivery.rejected"]
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    rejection_id: CanonicalUUID
    deployment_namespace: Namespace
    consumer_role: ConsumerRole
    body_digest: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
    byte_count: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
    error_code: RejectionCode
    created_at_ms: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]


def parse_broker_diagnostic(raw: bytes) -> BrokerDiagnostic:
    """Bound decoding and never surface untrusted input in errors."""
    if type(raw) is not bytes or len(raw) > 4096:
        raise ValueError("invalid_broker_diagnostic")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        return BrokerDiagnostic.model_validate(value)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("invalid_broker_diagnostic") from None
