"""Normalize Host write outcomes into durable, content-free evidence."""

from collections.abc import Mapping
from datetime import UTC, datetime

from agent_core.domain.effect_dispatch import EffectBusinessOutcome, EffectTransportOutcome
from agent_core.domain.host_effect_receipts import HostEffectReceipt, HostEffectStatus


def host_effect_metadata(body: Mapping[str, object]) -> dict[str, object]:
    nested = body.get("metadata")
    metadata = nested if isinstance(nested, Mapping) else {}

    def value(*keys: str) -> object:
        for source in (body, metadata):
            for key in keys:
                candidate = source.get(key)
                if candidate is not None:
                    return candidate
        return None

    raw_status = value("effectStatus", "effect_status")
    provider_operation_id = value("providerOperationId", "provider_operation_id")
    business_revision = value("businessRevision", "business_revision")
    raw_status_text = raw_status if isinstance(raw_status, str) else ""
    normalized_status = {
        "applied": HostEffectStatus.SUCCEEDED,
        "rejected": HostEffectStatus.FAILED_NO_EFFECT,
    }.get(raw_status_text, raw_status_text)
    receipt: HostEffectReceipt | None = None
    try:
        receipt = HostEffectReceipt(
            provider_operation_id=(
                provider_operation_id.strip()
                if isinstance(provider_operation_id, str)
                else ""
            ),
            business_revision=(
                business_revision.strip()
                if isinstance(business_revision, str) and business_revision.strip()
                else None
            ),
            effect_status=HostEffectStatus(str(normalized_status)),
            evidence_digest=(
                str(value("evidenceDigest", "evidence_digest"))[:128]
                if value("evidenceDigest", "evidence_digest") is not None
                else None
            ),
            received_at=datetime.now(UTC),
        )
    except ValueError:
        pass
    applied = receipt is not None and receipt.effect_status is HostEffectStatus.SUCCEEDED
    rejected = receipt is not None and receipt.effect_status is HostEffectStatus.FAILED_NO_EFFECT
    outcome = (
        EffectBusinessOutcome.APPLIED
        if applied
        else EffectBusinessOutcome.REJECTED
        if rejected
        else EffectBusinessOutcome.UNKNOWN
    )
    result: dict[str, object] = {
        "transport_outcome": EffectTransportOutcome.RETURNED.value,
        "business_outcome": outcome.value,
    }
    if isinstance(provider_operation_id, str) and provider_operation_id.strip():
        result["provider_operation_id"] = provider_operation_id.strip()[:256]
        result["mutation_effect_id"] = provider_operation_id.strip()[:256]
    if isinstance(business_revision, str) and business_revision.strip():
        result["business_revision"] = business_revision.strip()[:256]
        result["commit_version"] = business_revision.strip()[:256]
    if receipt is not None:
        result["host_effect_receipt"] = receipt.model_dump(mode="json")
        result["host_effect_receipt_digest"] = receipt.receipt_digest
    return result


def failure_outcomes(reason: str, metadata: Mapping[str, object]) -> dict[str, str]:
    if "transport_outcome" in metadata and "business_outcome" in metadata:
        return {}
    if reason == "timeout":
        return {
            "transport_outcome": EffectTransportOutcome.TIMED_OUT.value,
            "business_outcome": EffectBusinessOutcome.UNKNOWN.value,
        }
    if reason in {"transport_error", "host_transport_error", "manifest_http_error"}:
        return {
            "transport_outcome": EffectTransportOutcome.UNAVAILABLE.value,
            "business_outcome": EffectBusinessOutcome.UNKNOWN.value,
        }
    status = metadata.get("http_status")
    rejected = isinstance(status, int) and 400 <= status < 500
    rejected_reasons = {
        "unknown_host_tool",
        "missing_required_argument",
        "scope_denied",
        "resource_denied",
        "idempotency_required",
        "grant_expired",
    }
    return {
        "transport_outcome": EffectTransportOutcome.RETURNED.value,
        "business_outcome": (
            EffectBusinessOutcome.REJECTED.value
            if rejected or reason in rejected_reasons
            else EffectBusinessOutcome.UNKNOWN.value
        ),
    }
