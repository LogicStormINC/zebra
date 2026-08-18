"""Host write effects: uncertain recording and bounded reconciliation.

AL-HOST-EFFECT-01 / ADR-017 §6.3: when a Host write outcome is unknown
(timeout, connection drop), Zebra records ``uncertain`` and reconciles by
``provider_operation_id`` through the profile's reconcile endpoint. Blind
retries are forbidden; transport failures keep the effect uncertain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from agent_core.domain.host_connectors import HostConnectorProfileVersion
from agent_core.domain.host_effect_receipts import (
    HostEffectReceipt,
    HostEffectStatus,
    uncertain_receipt,
)

MAX_PROVIDER_OPERATION_ID_LENGTH = 256


@dataclass(frozen=True)
class HostEffectWriteOutcome:
    """What one Host write attempt produced."""

    provider_operation_id: str
    receipt: HostEffectReceipt
    attempts: int = 1


class HostReconcileTransport(Protocol):
    """One bounded reconcile request against the pinned profile path."""

    def request(
        self,
        url: str,
        *,
        provider_operation_id: str,
        timeout_seconds: float,
    ) -> tuple[int, dict[str, object]]: ...


class HostEffectReconciler:
    """Reconcile uncertain Host writes through the pinned profile path."""

    def __init__(self, transport: HostReconcileTransport) -> None:
        self._transport = transport

    def reconcile(
        self,
        profile: HostConnectorProfileVersion,
        uncertain: HostEffectReceipt,
        *,
        timeout_seconds: float = 10.0,
    ) -> HostEffectReceipt:
        """Return a settled receipt or keep the effect uncertain.

        A transport failure or an unparseable response never invents an
        outcome: the receipt stays ``uncertain`` for the next bounded pass.
        """

        if uncertain.effect_status is not HostEffectStatus.UNCERTAIN:
            return uncertain
        if not profile.reconcile_path_template:
            return uncertain
        try:
            status_code, body = self._transport.request(
                profile.base_uri + profile.reconcile_path_template,
                provider_operation_id=uncertain.provider_operation_id,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            return uncertain
        if not 200 <= status_code < 300 or not isinstance(body, dict):
            return uncertain
        raw_status = str(body.get("effectStatus", body.get("effect_status", "")))
        try:
            settled = HostEffectStatus(raw_status)
        except ValueError:
            return uncertain
        if settled is HostEffectStatus.UNCERTAIN:
            return uncertain
        revision = body.get("businessRevision", body.get("business_revision"))
        return HostEffectReceipt(
            provider_operation_id=uncertain.provider_operation_id,
            business_revision=str(revision) if revision is not None else None,
            effect_status=settled,
            evidence_digest=uncertain.evidence_digest,
            reconciliation_note=str(
                body.get("note", "reconciled through the pinned profile path")
            )[:512],
            received_at=uncertain.received_at,
        )


def record_uncertain_write(provider_operation_id: str) -> HostEffectWriteOutcome:
    """Record an unknown write outcome; never retry blindly."""

    text = provider_operation_id.strip()
    if not text or len(text) > MAX_PROVIDER_OPERATION_ID_LENGTH:
        raise ValueError("provider operation id must be bounded and non-blank")
    return HostEffectWriteOutcome(
        provider_operation_id=text,
        receipt=uncertain_receipt(text),
    )


def settle_write(
    provider_operation_id: str,
    *,
    succeeded: bool,
    business_revision: str | None,
) -> HostEffectWriteOutcome:
    """Record a deterministic in-band write outcome."""

    text = provider_operation_id.strip()
    if not text or len(text) > MAX_PROVIDER_OPERATION_ID_LENGTH:
        raise ValueError("provider operation id must be bounded and non-blank")
    if succeeded and not business_revision:
        raise ValueError("succeeded host effects require a business revision")
    return HostEffectWriteOutcome(
        provider_operation_id=text,
        receipt=HostEffectReceipt(
            provider_operation_id=text,
            business_revision=business_revision,
            effect_status=(
                HostEffectStatus.SUCCEEDED if succeeded else HostEffectStatus.FAILED_NO_EFFECT
            ),
            reconciliation_note=None if succeeded else "host reported no effect",
            received_at=datetime.now(UTC),
        ),
    )
