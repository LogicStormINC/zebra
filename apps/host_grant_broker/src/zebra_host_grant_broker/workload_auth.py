from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from zebra_host_grant_broker.config import BrokerSettings
from zebra_host_grant_broker.trench_session import TrenchViewer


class WorkloadAuthError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedWorkload:
    identity: str
    nonce: str
    issued_at: int
    viewer: TrenchViewer

    @property
    def grant_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"zebra-grant:{self.identity}:{self.nonce}"))


def verify_workload(
    settings: BrokerSettings,
    body: dict[str, object],
    *,
    identity: str | None,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    now: int | None = None,
) -> VerifiedWorkload:
    normalized_identity = (identity or "").strip()
    normalized_nonce = (nonce or "").strip()
    if normalized_identity not in settings.workload_identities:
        raise WorkloadAuthError("workload_identity_rejected")
    if not settings.workload_shared_secret:
        raise WorkloadAuthError("workload_exchange_disabled")
    if not normalized_nonce or len(normalized_nonce) > 128:
        raise WorkloadAuthError("workload_nonce_invalid")
    try:
        issued_at = int(timestamp or "")
    except ValueError as exc:
        raise WorkloadAuthError("workload_timestamp_invalid") from exc
    current = int(time.time()) if now is None else now
    if abs(current - issued_at) > settings.workload_clock_skew_seconds:
        raise WorkloadAuthError("workload_timestamp_expired")
    canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    signed = f"{issued_at}\n{normalized_nonce}\n{digest}".encode()
    expected = hmac.new(
        settings.workload_shared_secret.encode(), signed, hashlib.sha256
    ).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature.strip().lower()):
        raise WorkloadAuthError("workload_signature_invalid")
    principal = body.get("principal")
    if not isinstance(principal, dict):
        raise WorkloadAuthError("workload_principal_invalid")
    user_id = _text(principal.get("userId"), "workload_principal_invalid")
    workspace_id = _text(principal.get("workspaceId"), "workload_workspace_invalid")
    raw_sources = principal.get("activeSourceIds", [])
    if not isinstance(raw_sources, list) or len(raw_sources) > 4096:
        raise WorkloadAuthError("workload_sources_invalid")
    sources = frozenset(_text(value, "workload_sources_invalid") for value in raw_sources)
    return VerifiedWorkload(
        identity=normalized_identity,
        nonce=normalized_nonce,
        issued_at=issued_at,
        viewer=TrenchViewer(user_id=user_id, workspace_id=workspace_id, active_source_ids=sources),
    )


def _text(value: object, error: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise WorkloadAuthError(error)
    return value.strip()
