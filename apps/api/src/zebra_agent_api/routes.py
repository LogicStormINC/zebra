from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.responses import ApiResponse


@dataclass(frozen=True)
class RouteRequest:
    method: str
    path: str
    body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    query: dict[str, str] | None = None


@dataclass(frozen=True)
class RouteAdapter:
    app: ZebraAgentApi

    def handle(self, request: RouteRequest) -> ApiResponse:
        method = request.method.upper()
        if method == "GET" and request.path == "/health":
            return self.app.health()
        if method == "GET" and request.path == "/sessions":
            return self.app.list_sessions(request.query or {})
        if method == "POST" and request.path == "/sessions":
            return self.app.create_session(request.body or {})
        if method == "POST" and request.path.startswith("/approvals/"):
            parts = _approval_path_parts(request.path)
            if len(parts) == 2 and parts[1] == "approve":
                return self.app.approve(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "reject":
                return self.app.reject(parts[0], request.body or {})
        if method == "GET" and request.path == "/approvals":
            return self.app.list_approvals()
        if method == "GET" and request.path.startswith("/approvals/"):
            parts = _approval_path_parts(request.path)
            if len(parts) == 1:
                return self.app.get_approval(parts[0])
        if method == "GET" and request.path.startswith("/users/"):
            parts = _users_path_parts(request.path)
            if len(parts) == 2 and parts[1] == "memory":
                return self.app.get_user_memory(parts[0])
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "queue":
                return self.app.get_user_memory_queue(parts[0])
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "queue-summary":
                return self.app.get_user_memory_queue_summary(parts[0])
        if method == "POST" and request.path.startswith("/users/"):
            parts = _users_path_parts(request.path)
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "review-queue-preview":
                return self.app.preview_user_memory_queue(parts[0], request.body or {})
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "review-queue":
                return self.app.review_user_memory_queue(parts[0], request.body or {})
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "bulk-review":
                return self.app.bulk_review_user_memory(parts[0], request.body or {})
            if len(parts) == 4 and parts[1] == "memory" and parts[3] == "confirm":
                return self.app.confirm_user_memory(parts[0], parts[2], request.body or {})
            if len(parts) == 4 and parts[1] == "memory" and parts[3] == "expire":
                return self.app.expire_user_memory(parts[0], parts[2], request.body or {})
        if method == "GET" and request.path.startswith("/tenants/"):
            parts = _tenants_path_parts(request.path)
            if len(parts) == 2 and parts[1] == "memory":
                return self.app.get_tenant_memory(parts[0])
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "queue":
                return self.app.get_tenant_memory_queue(parts[0])
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "queue-summary":
                return self.app.get_tenant_memory_queue_summary(parts[0])
        if method == "POST" and request.path.startswith("/tenants/"):
            parts = _tenants_path_parts(request.path)
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "review-queue-preview":
                return self.app.preview_tenant_memory_queue(parts[0], request.body or {})
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "review-queue":
                return self.app.review_tenant_memory_queue(parts[0], request.body or {})
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "bulk-review":
                return self.app.bulk_review_tenant_memory(parts[0], request.body or {})
            if len(parts) == 4 and parts[1] == "memory" and parts[3] == "confirm":
                return self.app.confirm_tenant_memory(parts[0], parts[2], request.body or {})
            if len(parts) == 4 and parts[1] == "memory" and parts[3] == "expire":
                return self.app.expire_tenant_memory(parts[0], parts[2], request.body or {})
        if method == "POST" and request.path.startswith("/sessions/"):
            parts = _session_path_parts(request.path)
            if len(parts) == 2 and parts[1] == "messages":
                return self.app.append_session_message(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "cancel":
                return self.app.cancel_session(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "suspend":
                return self.app.suspend_session(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "resume":
                return self.app.resume_session(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-overview":
                return self.app.get_memory_operations_overview(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-governance":
                return self.app.get_memory_review_governance_signals(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-aging":
                return self.app.get_memory_backlog_aging_signals(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-velocity":
                return self.app.get_memory_review_velocity_signals(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-pressure":
                return self.app.get_memory_backlog_pressure_signals(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-action-hints":
                return self.app.get_memory_pressure_action_hints(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-escalations":
                return self.app.get_memory_pressure_escalation_recommendations(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-follow-up-windows":
                return self.app.get_memory_escalation_follow_up_windows(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-flags":
                return self.app.get_memory_follow_up_overdue_flags(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-age-buckets":
                return self.app.get_memory_overdue_age_buckets(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-overdue-types":
                return self.app.get_memory_overdue_type_rollups(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-overdue-visibility":
                return self.app.get_memory_overdue_visibility_rollups(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-trends":
                return self.app.get_memory_overdue_trend_signals(parts[0], request.body or {})
            if len(parts) == 2 and parts[1] == "memory-overdue-interventions":
                return self.app.get_memory_overdue_intervention_hints(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-escalation-lanes":
                return self.app.get_memory_overdue_escalation_lanes(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-recovery-paths":
                return self.app.get_memory_overdue_recovery_paths(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-resolution-checkpoints":
                return self.app.get_memory_overdue_resolution_checkpoints(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-resolution-outcomes":
                return self.app.get_memory_overdue_resolution_outcomes(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-closure-decisions":
                return self.app.get_memory_overdue_closure_decisions(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-archive-recommendations":
                return self.app.get_memory_overdue_archive_recommendations(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-retention-guidance":
                return self.app.get_memory_overdue_retention_guidance(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-retention-windows":
                return self.app.get_memory_overdue_retention_windows(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-retention-breaches":
                return self.app.get_memory_overdue_retention_breaches(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-retention-breach-aging":
                return self.app.get_memory_overdue_retention_breach_aging(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-retention-breach-actions":
                return self.app.get_memory_overdue_retention_breach_actions(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-retention-breach-lanes":
                return self.app.get_memory_overdue_retention_breach_lanes(
                    parts[0], request.body or {}
                )
            if len(parts) == 2 and parts[1] == "memory-overdue-retention-breach-owner-targets":
                return self.app.get_memory_overdue_retention_breach_owner_targets(
                    parts[0], request.body or {}
                )
            if (
                len(parts) == 2
                and parts[1] == "memory-overdue-retention-breach-follow-through-modes"
            ):
                return self.app.get_memory_overdue_retention_breach_follow_through_modes(
                    parts[0], request.body or {}
                )
            if (
                len(parts) == 2
                and parts[1] == "memory-overdue-retention-breach-follow-through-outcomes"
            ):
                return self.app.get_memory_overdue_retention_breach_follow_through_outcomes(
                    parts[0], request.body or {}
                )
            if (
                len(parts) == 2
                and parts[1]
                == "memory-overdue-retention-breach-follow-through-completion-states"
            ):
                return (
                    self.app.get_memory_overdue_retention_breach_follow_through_completion_states(
                        parts[0], request.body or {}
                    )
                )
            if (
                len(parts) == 2
                and parts[1]
                == "memory-overdue-retention-breach-follow-through-verification-states"
            ):
                return (
                    self.app.get_memory_overdue_retention_breach_follow_through_verification_states(
                        parts[0], request.body or {}
                    )
                )
            if (
                len(parts) == 2
                and parts[1]
                == "memory-overdue-retention-breach-follow-through-verification-outcomes"
            ):
                return (
                    self.app.get_memory_overdue_retention_breach_follow_through_verification_outcomes(
                        parts[0], request.body or {}
                    )
                )
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "review-queue-preview":
                return self.app.preview_session_memory_queue(parts[0], request.body or {})
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "review-queue":
                return self.app.review_session_memory_queue(parts[0], request.body or {})
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "bulk-review":
                return self.app.bulk_review_session_memory(parts[0], request.body or {})
            if len(parts) == 4 and parts[1] == "memory" and parts[3] == "confirm":
                return self.app.confirm_session_memory(parts[0], parts[2], request.body or {})
            if len(parts) == 4 and parts[1] == "memory" and parts[3] == "expire":
                return self.app.expire_session_memory(parts[0], parts[2], request.body or {})
            if len(parts) == 4 and parts[1] == "artifacts" and parts[3] == "prune":
                return self.app.prune_session_artifact(parts[0], parts[2])
            if len(parts) == 2 and parts[1] == "commit":
                return self.app.commit_session(
                    parts[0],
                    request.body or {},
                    idempotency_key=_idempotency_key(request),
                )
            if len(parts) == 2 and parts[1] == "pull-request":
                return self.app.open_session_pull_request(
                    parts[0],
                    request.body or {},
                    idempotency_key=_idempotency_key(request),
                )
        if method == "GET" and request.path.startswith("/sessions/"):
            parts = _session_path_parts(request.path)
            if parts == ():
                return _not_found(request)
            if len(parts) == 1:
                return self.app.get_session(parts[0])
            if len(parts) == 2 and parts[1] == "stream":
                return self.app.get_session_stream(parts[0])
            if len(parts) == 2 and parts[1] == "diff":
                return self.app.get_session_diff(parts[0])
            if len(parts) == 2 and parts[1] == "memory":
                return self.app.get_session_memory(parts[0])
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "queue":
                return self.app.get_session_memory_queue(parts[0])
            if len(parts) == 3 and parts[1] == "memory" and parts[2] == "queue-summary":
                return self.app.get_session_memory_queue_summary(parts[0])
            if len(parts) == 2 and parts[1] == "artifacts":
                return self.app.get_session_artifacts(parts[0])
            if len(parts) == 3 and parts[1] == "artifacts":
                return self.app.get_session_artifact_detail(parts[0], parts[2])
            if len(parts) == 4 and parts[1] == "artifacts" and parts[3] == "content":
                return self.app.get_session_artifact_content(parts[0], parts[2])
            if len(parts) == 2 and parts[1] == "delivery-audit":
                return self.app.get_session_delivery_audit(parts[0])
            return _not_found(request)
        return _not_found(request)


def _session_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/sessions/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _approval_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/approvals/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _users_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/users/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _tenants_path_parts(path: str) -> tuple[str, ...]:
    suffix = path.removeprefix("/tenants/")
    if not suffix:
        return ()
    return tuple(part for part in suffix.split("/") if part)


def _idempotency_key(request: RouteRequest) -> str | None:
    if request.headers is None:
        return None
    for name, value in request.headers.items():
        if name.lower() == "idempotency-key" and value.strip():
            return value.strip()
    return None


def _not_found(request: RouteRequest) -> ApiResponse:
    return ApiResponse(
        status_code=404,
        body={
            "method": request.method.upper(),
            "path": request.path,
            "status": "not_found",
        },
    )
