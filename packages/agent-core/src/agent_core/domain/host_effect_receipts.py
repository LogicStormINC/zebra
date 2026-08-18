"""Host effect receipts: bounded, content-free evidence of a Host write.

ADR-017 / plan section 6: when a Host write outcome is unknown (timeout,
connection drop), Zebra records ``uncertain`` and reconciles by
provider operation id. Blind retries are forbidden. Receipts never carry
business payloads or secrets — only digests and status.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PROVIDER_OPERATION_ID_LENGTH = 256
MAX_BUSINESS_REVISION_LENGTH = 256
MAX_EVIDENCE_DIGEST_LENGTH = 128
MAX_RECONCILIATION_NOTE_LENGTH = 512


class HostEffectStatus(StrEnum):
    """Deterministic Host-side outcome of one effect operation."""

    SUCCEEDED = "succeeded"
    FAILED_NO_EFFECT = "failed_no_effect"
    UNCERTAIN = "uncertain"


class HostEffectReceipt(BaseModel):
    """Canonical result retained for safe reconciliation and replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_operation_id: str = Field(min_length=1, max_length=MAX_PROVIDER_OPERATION_ID_LENGTH)
    business_revision: str | None = Field(
        default=None, max_length=MAX_BUSINESS_REVISION_LENGTH
    )
    effect_status: HostEffectStatus
    evidence_digest: str | None = Field(default=None, max_length=MAX_EVIDENCE_DIGEST_LENGTH)
    reconciliation_note: str | None = Field(
        default=None, max_length=MAX_RECONCILIATION_NOTE_LENGTH
    )
    received_at: datetime

    @model_validator(mode="after")
    def _validate_status_evidence(self) -> Self:
        if self.received_at.tzinfo is None:
            raise ValueError("receipt received_at must be timezone-aware")
        if self.effect_status is HostEffectStatus.SUCCEEDED and not self.business_revision:
            raise ValueError("succeeded effects must record a business revision")
        if self.evidence_digest is not None and not self.evidence_digest.strip():
            raise ValueError("evidence digest must be non-blank when present")
        return self

    @property
    def reconciled(self) -> bool:
        return self.effect_status is not HostEffectStatus.UNCERTAIN

    @property
    def receipt_digest(self) -> str:
        canonical = {
            "providerOperationId": self.provider_operation_id,
            "businessRevision": self.business_revision,
            "effectStatus": self.effect_status.value,
            "evidenceDigest": self.evidence_digest,
            "receivedAt": self.received_at.astimezone(UTC).isoformat(),
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def uncertain_receipt(
    provider_operation_id: str,
    *,
    received_at: datetime | None = None,
) -> HostEffectReceipt:
    """Record an unknown write outcome pending reconciliation."""

    return HostEffectReceipt(
        provider_operation_id=provider_operation_id,
        effect_status=HostEffectStatus.UNCERTAIN,
        received_at=received_at or datetime.now(UTC),
    )
