from datetime import UTC, datetime
from uuid import UUID

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.identifiers import SessionId
from agent_core.ports import DeliveryAuditStorePort

from zebra_agent_api.responses import ApiResponse


def record_delivery_audit(
    *,
    store: DeliveryAuditStorePort,
    session_id: str,
    action: str,
    response: ApiResponse,
    policy_profile: str | None = None,
    idempotency_key: str | None = None,
    result_metadata: dict[str, object] | None = None,
) -> None:
    metadata = _metadata_from_response(action, response)
    if result_metadata:
        metadata.update(result_metadata)
    store.append(
        DeliveryAuditRecord(
            session_id=SessionId(UUID(session_id)),
            action=action,
            status=_status_from_response(action, response),
            status_code=response.status_code,
            policy_profile=policy_profile,
            idempotency_key=idempotency_key,
            result_metadata=metadata,
            created_at=datetime.now(UTC),
        )
    )


def _status_from_response(action: str, response: ApiResponse) -> str:
    if action == "session.commit" and response.body.get("committed") is True:
        return "committed"
    if action == "session.pull_request":
        pull_request = response.body.get("pull_request")
        if isinstance(pull_request, dict):
            status = pull_request.get("status")
            if isinstance(status, str) and status.strip():
                return status
    status = response.body.get("status")
    if isinstance(status, str) and status.strip():
        return status
    return "unknown"


def _metadata_from_response(action: str, response: ApiResponse) -> dict[str, object]:
    if action == "session.commit":
        return {
            "commit_sha": response.body.get("commit_sha"),
            "message": response.body.get("message"),
            "reason": response.body.get("reason"),
        }
    pull_request = response.body.get("pull_request")
    if isinstance(pull_request, dict):
        return {
            "provider": pull_request.get("provider"),
            "status": pull_request.get("status"),
            "commit_sha": pull_request.get("commit_sha"),
            "dry_run": pull_request.get("dry_run"),
            "url": pull_request.get("url"),
            "credential_source": pull_request.get("credential_source"),
            "credential_backend": pull_request.get("credential_backend"),
            "route": pull_request.get("route"),
            "proxy_target": pull_request.get("proxy_target"),
            "proxy_transport": pull_request.get("proxy_transport"),
        }
    return {"reason": response.body.get("reason")}
