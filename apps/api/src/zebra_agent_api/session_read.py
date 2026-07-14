from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlparse
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_runtime import WorkspaceDiffError, WorkspaceDiffService
from agent_storage import (
    SessionArtifact,
    SQLiteArtifactPayloadStore,
    SQLiteArtifactStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    payload_for_artifact_uri,
    serialize_artifact_lifecycle,
    serialize_artifact_retrieval,
    serialize_session_artifact_projection,
)

from zebra_agent_api.artifact_access import (
    ArtifactAccessContext,
    build_artifact_access_metadata,
    build_artifact_policy_denied_response,
    build_artifact_unavailable_response,
    classify_session_artifact_access,
    serialize_artifact_access,
)
from zebra_agent_api.delivery_audit import record_delivery_audit
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_backlog_aging_signals,
    read_repo_memory_backlog_pressure_signals,
    read_repo_memory_escalation_follow_up_windows,
    read_repo_memory_follow_up_overdue_flags,
    read_repo_memory_governance_signals,
    read_repo_memory_inventory,
    read_repo_memory_overdue_age_buckets,
    read_repo_memory_overdue_archive_recommendations,
    read_repo_memory_overdue_closure_decisions,
    read_repo_memory_overdue_escalation_lanes,
    read_repo_memory_overdue_intervention_hints,
    read_repo_memory_overdue_recovery_paths,
    read_repo_memory_overdue_resolution_checkpoints,
    read_repo_memory_overdue_resolution_outcomes,
    read_repo_memory_overdue_retention_breach_actions,
    read_repo_memory_overdue_retention_breach_aging,
    read_repo_memory_overdue_retention_breach_follow_through_completion_states,
    read_repo_memory_overdue_retention_breach_follow_through_modes,
    read_repo_memory_overdue_retention_breach_follow_through_outcomes,
    read_repo_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_repo_memory_overdue_retention_breach_follow_through_verification_states,
    read_repo_memory_overdue_retention_breach_lanes,
    read_repo_memory_overdue_retention_breach_owner_targets,
    read_repo_memory_overdue_retention_breaches,
    read_repo_memory_overdue_retention_guidance,
    read_repo_memory_overdue_retention_windows,
    read_repo_memory_overdue_trend_signals,
    read_repo_memory_overdue_type_rollups,
    read_repo_memory_overdue_visibility_rollups,
    read_repo_memory_pressure_action_hints,
    read_repo_memory_pressure_escalation_recommendations,
    read_repo_memory_queue,
    read_repo_memory_queue_summary,
    read_repo_memory_review_velocity_signals,
    read_tenant_memory_backlog_aging_signals,
    read_tenant_memory_backlog_pressure_signals,
    read_tenant_memory_escalation_follow_up_windows,
    read_tenant_memory_follow_up_overdue_flags,
    read_tenant_memory_governance_signals,
    read_tenant_memory_inventory,
    read_tenant_memory_overdue_age_buckets,
    read_tenant_memory_overdue_archive_recommendations,
    read_tenant_memory_overdue_closure_decisions,
    read_tenant_memory_overdue_escalation_lanes,
    read_tenant_memory_overdue_intervention_hints,
    read_tenant_memory_overdue_recovery_paths,
    read_tenant_memory_overdue_resolution_checkpoints,
    read_tenant_memory_overdue_resolution_outcomes,
    read_tenant_memory_overdue_retention_breach_actions,
    read_tenant_memory_overdue_retention_breach_aging,
    read_tenant_memory_overdue_retention_breach_follow_through_completion_states,
    read_tenant_memory_overdue_retention_breach_follow_through_modes,
    read_tenant_memory_overdue_retention_breach_follow_through_outcomes,
    read_tenant_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_tenant_memory_overdue_retention_breach_follow_through_verification_states,
    read_tenant_memory_overdue_retention_breach_lanes,
    read_tenant_memory_overdue_retention_breach_owner_targets,
    read_tenant_memory_overdue_retention_breaches,
    read_tenant_memory_overdue_retention_guidance,
    read_tenant_memory_overdue_retention_windows,
    read_tenant_memory_overdue_trend_signals,
    read_tenant_memory_overdue_type_rollups,
    read_tenant_memory_overdue_visibility_rollups,
    read_tenant_memory_pressure_action_hints,
    read_tenant_memory_pressure_escalation_recommendations,
    read_tenant_memory_queue,
    read_tenant_memory_queue_summary,
    read_tenant_memory_review_velocity_signals,
    read_user_memory_backlog_aging_signals,
    read_user_memory_backlog_pressure_signals,
    read_user_memory_escalation_follow_up_windows,
    read_user_memory_follow_up_overdue_flags,
    read_user_memory_governance_signals,
    read_user_memory_inventory,
    read_user_memory_overdue_age_buckets,
    read_user_memory_overdue_archive_recommendations,
    read_user_memory_overdue_closure_decisions,
    read_user_memory_overdue_escalation_lanes,
    read_user_memory_overdue_intervention_hints,
    read_user_memory_overdue_recovery_paths,
    read_user_memory_overdue_resolution_checkpoints,
    read_user_memory_overdue_resolution_outcomes,
    read_user_memory_overdue_retention_breach_actions,
    read_user_memory_overdue_retention_breach_aging,
    read_user_memory_overdue_retention_breach_follow_through_completion_states,
    read_user_memory_overdue_retention_breach_follow_through_modes,
    read_user_memory_overdue_retention_breach_follow_through_outcomes,
    read_user_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_user_memory_overdue_retention_breach_follow_through_verification_states,
    read_user_memory_overdue_retention_breach_lanes,
    read_user_memory_overdue_retention_breach_owner_targets,
    read_user_memory_overdue_retention_breaches,
    read_user_memory_overdue_retention_guidance,
    read_user_memory_overdue_retention_windows,
    read_user_memory_overdue_trend_signals,
    read_user_memory_overdue_type_rollups,
    read_user_memory_overdue_visibility_rollups,
    read_user_memory_pressure_action_hints,
    read_user_memory_pressure_escalation_recommendations,
    read_user_memory_queue,
    read_user_memory_queue_summary,
    read_user_memory_review_velocity_signals,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_delivery_audit import SessionDeliveryAuditApi
from zebra_agent_api.session_payloads import parse_memory_overview_payload
from zebra_agent_api.session_summary import serialize_session_summary


def _parse_session_id(session_id: str) -> SessionId | ApiResponse:
    try:
        return SessionId(UUID(session_id))
    except ValueError:
        return ApiResponse(
            status_code=400,
            body={
                "session_id": session_id,
                "status": "invalid_request",
                "reason": "session_id must be a valid UUID",
            },
        )


@dataclass(frozen=True)
class SessionReadApi:
    database_path: Path

    def get_session(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        workspace = SQLiteWorkspaceProjectionStore(self.database_path).get_workspace(session_key)
        return ApiResponse(
            status_code=200,
            body=serialize_session_summary(session, workspace),
        )

    def get_session_stream(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={
                    "session_id": session_id,
                    "status": "not_found",
                },
            )
        events = SQLiteEventStore(self.database_path).list_for_session(session_key)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "events": [
                    {
                        "event_id": str(event.event_id),
                        "sequence": event.sequence,
                        "event_type": event.event_type.value,
                        "actor": event.actor.value,
                        "created_at": event.created_at.isoformat(),
                        "payload": event.payload,
                    }
                    for event in events
                ],
            },
        )

    def get_session_diff(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        workspace_root = session_workspace_root(
            SQLiteEventStore(self.database_path).list_for_session(session_key)
        )
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="diff_unavailable",
                reason="session workspace_root is unavailable",
            )
        try:
            diff = WorkspaceDiffService().read_diff(workspace_root)
        except WorkspaceDiffError as error:
            return conflict(
                session_id=session_id,
                status="diff_unavailable",
                reason=str(error),
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "workspace": str(diff.workspace_root),
                "clean": diff.clean,
                "git_status": diff.git_status,
                "diff": diff.diff,
            },
        )

    def get_session_memory(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "memories": read_repo_memory_inventory(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                ),
            },
        )

    def get_session_memory_queue(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "memories": read_repo_memory_queue(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                ),
            },
        )

    def get_session_memory_queue_summary(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                **read_repo_memory_queue_summary(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                ),
            },
        )

    def get_memory_operations_overview(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_queue_summary(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_queue_summary(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_queue_summary(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                    ),
                }
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "scope_count": len(scopes),
                "total_pending_count": _sum_pending_counts(scopes),
                "scopes": scopes,
            },
        )

    def get_memory_review_governance_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_governance_signals(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_governance_signals(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_governance_signals(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                    ),
                }
            )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "scope_count": len(scopes),
                "total_pending_count": _sum_pending_counts(scopes),
                "total_reviewed_count": _sum_reviewed_counts(scopes),
                "review_status_totals": _sum_status_counts(scopes),
                "scopes": scopes,
            },
        )

    def get_memory_backlog_aging_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(
            event.created_at for event in events
        )
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_backlog_aging_signals(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_backlog_aging_signals(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_backlog_aging_signals(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        oldest_pending = _oldest_pending_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "total_pending_count": _sum_pending_counts(scopes),
                "pending_age_bucket_totals": _sum_age_bucket_counts(scopes),
                "oldest_pending_scope_kind": (
                    None if oldest_pending is None else oldest_pending["scope_kind"]
                ),
                "oldest_pending_scope_id": (
                    None if oldest_pending is None else oldest_pending["scope_id"]
                ),
                "oldest_pending_memory_id": (
                    None if oldest_pending is None else oldest_pending["memory_id"]
                ),
                "oldest_pending_captured_at": (
                    None if oldest_pending is None else oldest_pending["captured_at"]
                ),
                "oldest_pending_age_seconds": (
                    None if oldest_pending is None else oldest_pending["age_seconds"]
                ),
                "oldest_pending_age_days": (
                    None if oldest_pending is None else oldest_pending["age_days"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_review_velocity_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_review_velocity_signals(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_review_velocity_signals(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_review_velocity_signals(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        latest_review = _latest_review_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "total_reviewed_count": _sum_reviewed_counts(scopes),
                "total_reviewed_last_24h_count": _sum_recent_review_counts(
                    scopes,
                    "reviewed_last_24h_count",
                ),
                "total_reviewed_last_7d_count": _sum_recent_review_counts(
                    scopes,
                    "reviewed_last_7d_count",
                ),
                "total_reviewed_last_30d_count": _sum_recent_review_counts(
                    scopes,
                    "reviewed_last_30d_count",
                ),
                "latest_review_scope_kind": (
                    None if latest_review is None else latest_review["scope_kind"]
                ),
                "latest_review_scope_id": (
                    None if latest_review is None else latest_review["scope_id"]
                ),
                "latest_reviewed_at": (
                    None if latest_review is None else latest_review["recorded_at"]
                ),
                "latest_review_status": (
                    None if latest_review is None else latest_review["status"]
                ),
                "latest_review_operator": (
                    None if latest_review is None else latest_review["operator"]
                ),
                "latest_review_window": (
                    None if latest_review is None else latest_review["window"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_backlog_pressure_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_backlog_pressure_signals(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_backlog_pressure_signals(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_backlog_pressure_signals(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_pressure = _highest_pressure_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "total_pending_count": _sum_pending_counts(scopes),
                "pending_age_bucket_totals": _sum_age_bucket_counts(scopes),
                "total_reviewed_last_24h_count": _sum_recent_review_counts(
                    scopes,
                    "reviewed_last_24h_count",
                ),
                "total_reviewed_last_7d_count": _sum_recent_review_counts(
                    scopes,
                    "reviewed_last_7d_count",
                ),
                "pressure_level_counts": _sum_pressure_level_counts(scopes),
                "highest_pressure_level": (
                    None if highest_pressure is None else highest_pressure["pressure_level"]
                ),
                "highest_pressure_scope_kind": (
                    None if highest_pressure is None else highest_pressure["scope_kind"]
                ),
                "highest_pressure_scope_id": (
                    None if highest_pressure is None else highest_pressure["scope_id"]
                ),
                "highest_pressure_reasons": (
                    [] if highest_pressure is None else highest_pressure["pressure_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_pressure_action_hints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_pressure_action_hints(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_pressure_action_hints(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_pressure_action_hints(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_action = _highest_priority_action_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "action_hint_counts": _sum_action_hint_counts(scopes),
                "highest_priority_action_hint": (
                    None if highest_action is None else highest_action["action_hint"]
                ),
                "highest_priority_action_priority": (
                    None if highest_action is None else highest_action["action_priority"]
                ),
                "highest_priority_action_scope_kind": (
                    None if highest_action is None else highest_action["scope_kind"]
                ),
                "highest_priority_action_scope_id": (
                    None if highest_action is None else highest_action["scope_id"]
                ),
                "highest_priority_action_target_memory_id": (
                    None if highest_action is None else highest_action["target_memory_id"]
                ),
                "highest_priority_action_reasons": (
                    [] if highest_action is None else highest_action["action_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_pressure_escalation_recommendations(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_pressure_escalation_recommendations(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_pressure_escalation_recommendations(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_pressure_escalation_recommendations(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_escalation = _highest_priority_escalation_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "escalation_recommendation_counts": _sum_escalation_recommendation_counts(
                    scopes
                ),
                "highest_priority_escalation_recommendation": (
                    None
                    if highest_escalation is None
                    else highest_escalation["escalation_recommendation"]
                ),
                "highest_priority_escalation_priority": (
                    None
                    if highest_escalation is None
                    else highest_escalation["escalation_priority"]
                ),
                "highest_priority_escalation_scope_kind": (
                    None if highest_escalation is None else highest_escalation["scope_kind"]
                ),
                "highest_priority_escalation_scope_id": (
                    None if highest_escalation is None else highest_escalation["scope_id"]
                ),
                "highest_priority_escalation_target_memory_id": (
                    None
                    if highest_escalation is None
                    else highest_escalation["target_memory_id"]
                ),
                "highest_priority_escalation_reasons": (
                    []
                    if highest_escalation is None
                    else highest_escalation["escalation_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_escalation_follow_up_windows(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_escalation_follow_up_windows(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_escalation_follow_up_windows(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_escalation_follow_up_windows(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_follow_up = _highest_priority_follow_up_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "follow_up_window_counts": _sum_follow_up_window_counts(scopes),
                "highest_priority_follow_up_window": (
                    None if highest_follow_up is None else highest_follow_up["follow_up_window"]
                ),
                "highest_priority_follow_up_priority": (
                    None
                    if highest_follow_up is None
                    else highest_follow_up["follow_up_priority"]
                ),
                "highest_priority_follow_up_scope_kind": (
                    None if highest_follow_up is None else highest_follow_up["scope_kind"]
                ),
                "highest_priority_follow_up_scope_id": (
                    None if highest_follow_up is None else highest_follow_up["scope_id"]
                ),
                "highest_priority_follow_up_due_at": (
                    None if highest_follow_up is None else highest_follow_up["due_at"]
                ),
                "highest_priority_follow_up_target_memory_id": (
                    None
                    if highest_follow_up is None
                    else highest_follow_up["target_memory_id"]
                ),
                "highest_priority_follow_up_reasons": (
                    [] if highest_follow_up is None else highest_follow_up["follow_up_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_follow_up_overdue_flags(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_follow_up_overdue_flags(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_follow_up_overdue_flags(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_follow_up_overdue_flags(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_overdue = _highest_priority_overdue_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "highest_priority_overdue_scope_kind": (
                    None if highest_overdue is None else highest_overdue["scope_kind"]
                ),
                "highest_priority_overdue_scope_id": (
                    None if highest_overdue is None else highest_overdue["scope_id"]
                ),
                "highest_priority_overdue_priority": (
                    None
                    if highest_overdue is None
                    else highest_overdue["follow_up_overdue_priority"]
                ),
                "highest_priority_overdue_since": (
                    None
                    if highest_overdue is None
                    else highest_overdue["follow_up_overdue_since"]
                ),
                "highest_priority_overdue_target_memory_id": (
                    None if highest_overdue is None else highest_overdue["target_memory_id"]
                ),
                "highest_priority_overdue_reasons": (
                    []
                    if highest_overdue is None
                    else highest_overdue["follow_up_overdue_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_age_buckets(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_age_buckets(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_age_buckets(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_age_buckets(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_overdue_age = _highest_priority_overdue_age_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_age_bucket_counts": _sum_overdue_age_bucket_counts(scopes),
                "highest_priority_overdue_age_bucket": (
                    None
                    if highest_overdue_age is None
                    else highest_overdue_age["overdue_age_bucket"]
                ),
                "highest_priority_overdue_age_scope_kind": (
                    None
                    if highest_overdue_age is None
                    else highest_overdue_age["scope_kind"]
                ),
                "highest_priority_overdue_age_scope_id": (
                    None if highest_overdue_age is None else highest_overdue_age["scope_id"]
                ),
                "highest_priority_overdue_age_seconds": (
                    None
                    if highest_overdue_age is None
                    else highest_overdue_age["overdue_age_seconds"]
                ),
                "highest_priority_overdue_age_days": (
                    None
                    if highest_overdue_age is None
                    else highest_overdue_age["overdue_age_days"]
                ),
                "highest_priority_overdue_age_target_memory_id": (
                    None
                    if highest_overdue_age is None
                    else highest_overdue_age["target_memory_id"]
                ),
                "highest_priority_overdue_age_reasons": (
                    []
                    if highest_overdue_age is None
                    else highest_overdue_age["overdue_age_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_type_rollups(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_type_rollups(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_type_rollups(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_type_rollups(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_overdue_type = _highest_priority_overdue_type_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_memory_type_counts": _sum_overdue_memory_type_counts(scopes),
                "highest_priority_overdue_memory_type": (
                    None
                    if highest_overdue_type is None
                    else highest_overdue_type["highest_overdue_memory_type"]
                ),
                "highest_priority_overdue_memory_type_count": (
                    None
                    if highest_overdue_type is None
                    else highest_overdue_type["highest_overdue_memory_type_count"]
                ),
                "highest_priority_overdue_type_scope_kind": (
                    None if highest_overdue_type is None else highest_overdue_type["scope_kind"]
                ),
                "highest_priority_overdue_type_scope_id": (
                    None if highest_overdue_type is None else highest_overdue_type["scope_id"]
                ),
                "highest_priority_overdue_type_target_memory_id": (
                    None
                    if highest_overdue_type is None
                    else highest_overdue_type["target_memory_id"]
                ),
                "highest_priority_overdue_target_memory_type": (
                    None
                    if highest_overdue_type is None
                    else highest_overdue_type["overdue_target_memory_type"]
                ),
                "highest_priority_overdue_type_reasons": (
                    []
                    if highest_overdue_type is None
                    else highest_overdue_type["overdue_type_rollup_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_visibility_rollups(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_visibility_rollups(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_visibility_rollups(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_visibility_rollups(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_overdue_visibility = _highest_priority_overdue_visibility_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_memory_visibility_counts": _sum_overdue_memory_visibility_counts(
                    scopes
                ),
                "highest_priority_overdue_memory_visibility": (
                    None
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility["highest_overdue_memory_visibility"]
                ),
                "highest_priority_overdue_memory_visibility_count": (
                    None
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility[
                        "highest_overdue_memory_visibility_count"
                    ]
                ),
                "highest_priority_overdue_visibility_scope_kind": (
                    None
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility["scope_kind"]
                ),
                "highest_priority_overdue_visibility_scope_id": (
                    None
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility["scope_id"]
                ),
                "highest_priority_overdue_visibility_target_memory_id": (
                    None
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility["target_memory_id"]
                ),
                "highest_priority_overdue_target_memory_visibility": (
                    None
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility["overdue_target_memory_visibility"]
                ),
                "highest_priority_overdue_visibility_reasons": (
                    []
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility["overdue_visibility_rollup_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_trend_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_trend_signals(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_trend_signals(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_trend_signals(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_overdue_trend = _highest_priority_overdue_trend_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_trend_signal_counts": _sum_overdue_trend_signal_counts(scopes),
                "highest_priority_overdue_trend_signal": (
                    None
                    if highest_overdue_trend is None
                    else highest_overdue_trend["overdue_trend_signal"]
                ),
                "highest_priority_overdue_trend_rank": (
                    None
                    if highest_overdue_trend is None
                    else highest_overdue_trend["overdue_trend_rank"]
                ),
                "highest_priority_overdue_trend_scope_kind": (
                    None if highest_overdue_trend is None else highest_overdue_trend["scope_kind"]
                ),
                "highest_priority_overdue_trend_scope_id": (
                    None if highest_overdue_trend is None else highest_overdue_trend["scope_id"]
                ),
                "highest_priority_overdue_trend_target_memory_id": (
                    None
                    if highest_overdue_trend is None
                    else highest_overdue_trend["target_memory_id"]
                ),
                "highest_priority_overdue_trend_reasons": (
                    []
                    if highest_overdue_trend is None
                    else highest_overdue_trend["overdue_trend_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_intervention_hints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_intervention_hints(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_intervention_hints(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_intervention_hints(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_intervention = _highest_priority_overdue_intervention_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_intervention_hint_counts": _sum_overdue_intervention_hint_counts(
                    scopes
                ),
                "highest_priority_overdue_intervention_hint": (
                    None
                    if highest_intervention is None
                    else highest_intervention["overdue_intervention_hint"]
                ),
                "highest_priority_overdue_intervention_priority": (
                    None
                    if highest_intervention is None
                    else highest_intervention["overdue_intervention_priority"]
                ),
                "highest_priority_overdue_intervention_scope_kind": (
                    None if highest_intervention is None else highest_intervention["scope_kind"]
                ),
                "highest_priority_overdue_intervention_scope_id": (
                    None if highest_intervention is None else highest_intervention["scope_id"]
                ),
                "highest_priority_overdue_intervention_target_memory_id": (
                    None
                    if highest_intervention is None
                    else highest_intervention["target_memory_id"]
                ),
                "highest_priority_overdue_intervention_reasons": (
                    []
                    if highest_intervention is None
                    else highest_intervention["overdue_intervention_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_escalation_lanes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_escalation_lanes(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_escalation_lanes(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_escalation_lanes(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_lane = _highest_priority_overdue_escalation_lane_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_escalation_lane_counts": _sum_overdue_escalation_lane_counts(
                    scopes
                ),
                "highest_priority_overdue_escalation_lane": (
                    None
                    if highest_lane is None
                    else highest_lane["overdue_escalation_lane"]
                ),
                "highest_priority_overdue_escalation_priority": (
                    None
                    if highest_lane is None
                    else highest_lane["overdue_escalation_priority"]
                ),
                "highest_priority_overdue_escalation_scope_kind": (
                    None if highest_lane is None else highest_lane["scope_kind"]
                ),
                "highest_priority_overdue_escalation_scope_id": (
                    None if highest_lane is None else highest_lane["scope_id"]
                ),
                "highest_priority_overdue_escalation_target_memory_id": (
                    None if highest_lane is None else highest_lane["target_memory_id"]
                ),
                "highest_priority_overdue_escalation_reasons": (
                    []
                    if highest_lane is None
                    else highest_lane["overdue_escalation_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_recovery_paths(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_recovery_paths(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_recovery_paths(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_recovery_paths(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_recovery = _highest_priority_overdue_recovery_path_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_recovery_path_counts": _sum_overdue_recovery_path_counts(scopes),
                "highest_priority_overdue_recovery_path": (
                    None
                    if highest_recovery is None
                    else highest_recovery["overdue_recovery_path"]
                ),
                "highest_priority_overdue_recovery_priority": (
                    None
                    if highest_recovery is None
                    else highest_recovery["overdue_recovery_priority"]
                ),
                "highest_priority_overdue_recovery_scope_kind": (
                    None if highest_recovery is None else highest_recovery["scope_kind"]
                ),
                "highest_priority_overdue_recovery_scope_id": (
                    None if highest_recovery is None else highest_recovery["scope_id"]
                ),
                "highest_priority_overdue_recovery_target_memory_id": (
                    None if highest_recovery is None else highest_recovery["target_memory_id"]
                ),
                "highest_priority_overdue_recovery_reasons": (
                    []
                    if highest_recovery is None
                    else highest_recovery["overdue_recovery_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_resolution_checkpoints(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_resolution_checkpoints(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_resolution_checkpoints(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_resolution_checkpoints(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_checkpoint = _highest_priority_overdue_resolution_checkpoint_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_resolution_checkpoint_counts": _sum_overdue_resolution_checkpoint_counts(
                    scopes
                ),
                "highest_priority_overdue_resolution_checkpoint": (
                    None
                    if highest_checkpoint is None
                    else highest_checkpoint["overdue_resolution_checkpoint"]
                ),
                "highest_priority_overdue_resolution_priority": (
                    None
                    if highest_checkpoint is None
                    else highest_checkpoint["overdue_resolution_priority"]
                ),
                "highest_priority_overdue_resolution_scope_kind": (
                    None
                    if highest_checkpoint is None
                    else highest_checkpoint["scope_kind"]
                ),
                "highest_priority_overdue_resolution_scope_id": (
                    None
                    if highest_checkpoint is None
                    else highest_checkpoint["scope_id"]
                ),
                "highest_priority_overdue_resolution_target_memory_id": (
                    None
                    if highest_checkpoint is None
                    else highest_checkpoint["target_memory_id"]
                ),
                "highest_priority_overdue_resolution_reasons": (
                    []
                    if highest_checkpoint is None
                    else highest_checkpoint["overdue_resolution_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_resolution_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_resolution_outcomes(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_resolution_outcomes(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_resolution_outcomes(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_outcome = _highest_priority_overdue_resolution_outcome_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_resolution_outcome_counts": _sum_overdue_resolution_outcome_counts(
                    scopes
                ),
                "highest_priority_overdue_resolution_outcome": (
                    None
                    if highest_outcome is None
                    else highest_outcome["overdue_resolution_outcome"]
                ),
                "highest_priority_overdue_resolution_outcome_priority": (
                    None
                    if highest_outcome is None
                    else highest_outcome["overdue_resolution_outcome_priority"]
                ),
                "highest_priority_overdue_resolution_outcome_scope_kind": (
                    None if highest_outcome is None else highest_outcome["scope_kind"]
                ),
                "highest_priority_overdue_resolution_outcome_scope_id": (
                    None if highest_outcome is None else highest_outcome["scope_id"]
                ),
                "highest_priority_overdue_resolution_outcome_target_memory_id": (
                    None if highest_outcome is None else highest_outcome["target_memory_id"]
                ),
                "highest_priority_overdue_resolution_outcome_reasons": (
                    []
                    if highest_outcome is None
                    else highest_outcome["overdue_resolution_outcome_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_closure_decisions(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_closure_decisions(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_closure_decisions(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_closure_decisions(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_decision = _highest_priority_overdue_closure_decision_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_closure_decision_counts": _sum_overdue_closure_decision_counts(
                    scopes
                ),
                "highest_priority_overdue_closure_decision": (
                    None
                    if highest_decision is None
                    else highest_decision["overdue_closure_decision"]
                ),
                "highest_priority_overdue_closure_priority": (
                    None
                    if highest_decision is None
                    else highest_decision["overdue_closure_priority"]
                ),
                "highest_priority_overdue_closure_scope_kind": (
                    None if highest_decision is None else highest_decision["scope_kind"]
                ),
                "highest_priority_overdue_closure_scope_id": (
                    None if highest_decision is None else highest_decision["scope_id"]
                ),
                "highest_priority_overdue_closure_target_memory_id": (
                    None if highest_decision is None else highest_decision["target_memory_id"]
                ),
                "highest_priority_overdue_closure_reasons": (
                    []
                    if highest_decision is None
                    else highest_decision["overdue_closure_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_archive_recommendations(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_archive_recommendations(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_archive_recommendations(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_archive_recommendations(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_recommendation = _highest_priority_overdue_archive_recommendation_scope(
            scopes
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_archive_recommendation_counts": _sum_overdue_archive_recommendation_counts(
                    scopes
                ),
                "highest_priority_overdue_archive_recommendation": (
                    None
                    if highest_recommendation is None
                    else highest_recommendation["overdue_archive_recommendation"]
                ),
                "highest_priority_overdue_archive_priority": (
                    None
                    if highest_recommendation is None
                    else highest_recommendation["overdue_archive_priority"]
                ),
                "highest_priority_overdue_archive_scope_kind": (
                    None
                    if highest_recommendation is None
                    else highest_recommendation["scope_kind"]
                ),
                "highest_priority_overdue_archive_scope_id": (
                    None
                    if highest_recommendation is None
                    else highest_recommendation["scope_id"]
                ),
                "highest_priority_overdue_archive_target_memory_id": (
                    None
                    if highest_recommendation is None
                    else highest_recommendation["target_memory_id"]
                ),
                "highest_priority_overdue_archive_reasons": (
                    []
                    if highest_recommendation is None
                    else highest_recommendation["overdue_archive_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_guidance(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_guidance(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_guidance(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_guidance(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_guidance = _highest_priority_overdue_retention_guidance_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_guidance_counts": _sum_overdue_retention_guidance_counts(
                    scopes
                ),
                "highest_priority_overdue_retention_guidance": (
                    None
                    if highest_guidance is None
                    else highest_guidance["overdue_retention_guidance"]
                ),
                "highest_priority_overdue_retention_priority": (
                    None
                    if highest_guidance is None
                    else highest_guidance["overdue_retention_priority"]
                ),
                "highest_priority_overdue_retention_scope_kind": (
                    None if highest_guidance is None else highest_guidance["scope_kind"]
                ),
                "highest_priority_overdue_retention_scope_id": (
                    None if highest_guidance is None else highest_guidance["scope_id"]
                ),
                "highest_priority_overdue_retention_bucket": (
                    None
                    if highest_guidance is None
                    else highest_guidance["overdue_retention_bucket"]
                ),
                "highest_priority_overdue_retention_target_memory_id": (
                    None
                    if highest_guidance is None
                    else highest_guidance["target_memory_id"]
                ),
                "highest_priority_overdue_retention_reasons": (
                    []
                    if highest_guidance is None
                    else highest_guidance["overdue_retention_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_windows(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_windows(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_windows(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_windows(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_window = _highest_priority_overdue_retention_window_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_window_counts": _sum_overdue_retention_window_counts(
                    scopes
                ),
                "highest_priority_overdue_retention_window": (
                    None
                    if highest_window is None
                    else highest_window["overdue_retention_window"]
                ),
                "highest_priority_overdue_retention_window_priority": (
                    None
                    if highest_window is None
                    else highest_window["overdue_retention_window_priority"]
                ),
                "highest_priority_overdue_retention_window_scope_kind": (
                    None if highest_window is None else highest_window["scope_kind"]
                ),
                "highest_priority_overdue_retention_window_scope_id": (
                    None if highest_window is None else highest_window["scope_id"]
                ),
                "highest_priority_overdue_retention_window_due_at": (
                    None if highest_window is None else highest_window["due_at"]
                ),
                "highest_priority_overdue_retention_window_target_memory_id": (
                    None
                    if highest_window is None
                    else highest_window["target_memory_id"]
                ),
                "highest_priority_overdue_retention_window_reasons": (
                    []
                    if highest_window is None
                    else highest_window["overdue_retention_window_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breaches(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breaches(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breaches(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breaches(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_breach = _highest_priority_overdue_retention_breach_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_counts": _sum_overdue_retention_breach_counts(
                    scopes
                ),
                "highest_priority_overdue_retention_breach": (
                    None
                    if highest_breach is None
                    else highest_breach["overdue_retention_breach"]
                ),
                "highest_priority_overdue_retention_breach_priority": (
                    None
                    if highest_breach is None
                    else highest_breach["overdue_retention_breach_priority"]
                ),
                "highest_priority_overdue_retention_breach_scope_kind": (
                    None if highest_breach is None else highest_breach["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_scope_id": (
                    None if highest_breach is None else highest_breach["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_due_at": (
                    None if highest_breach is None else highest_breach["due_at"]
                ),
                "highest_priority_overdue_retention_breach_target_memory_id": (
                    None
                    if highest_breach is None
                    else highest_breach["target_memory_id"]
                ),
                "highest_priority_overdue_retention_breach_reasons": (
                    []
                    if highest_breach is None
                    else highest_breach["overdue_retention_breach_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_aging(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_aging(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_aging(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_aging(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_aging = _highest_priority_overdue_retention_breach_aging_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_age_bucket_counts": (
                    _sum_overdue_retention_breach_age_bucket_counts(scopes)
                ),
                "highest_priority_overdue_retention_breach_age_bucket": (
                    None
                    if highest_aging is None
                    else highest_aging["overdue_retention_breach_age_bucket"]
                ),
                "highest_priority_overdue_retention_breach_age_scope_kind": (
                    None if highest_aging is None else highest_aging["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_age_scope_id": (
                    None if highest_aging is None else highest_aging["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_age_seconds": (
                    None
                    if highest_aging is None
                    else highest_aging["overdue_retention_breach_age_seconds"]
                ),
                "highest_priority_overdue_retention_breach_age_days": (
                    None
                    if highest_aging is None
                    else highest_aging["overdue_retention_breach_age_days"]
                ),
                "highest_priority_overdue_retention_breach_age_reasons": (
                    []
                    if highest_aging is None
                    else highest_aging["overdue_retention_breach_age_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_actions(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_actions(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_actions(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_actions(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_action = _highest_priority_overdue_retention_breach_action_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_action_counts": (
                    _sum_overdue_retention_breach_action_counts(scopes)
                ),
                "highest_priority_overdue_retention_breach_action": (
                    None
                    if highest_action is None
                    else highest_action["overdue_retention_breach_action"]
                ),
                "highest_priority_overdue_retention_breach_action_priority": (
                    None
                    if highest_action is None
                    else highest_action["overdue_retention_breach_action_priority"]
                ),
                "highest_priority_overdue_retention_breach_action_scope_kind": (
                    None if highest_action is None else highest_action["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_action_scope_id": (
                    None if highest_action is None else highest_action["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_action_target_memory_id": (
                    None
                    if highest_action is None
                    else highest_action["target_memory_id"]
                ),
                "highest_priority_overdue_retention_breach_action_reasons": (
                    []
                    if highest_action is None
                    else highest_action["overdue_retention_breach_action_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_lanes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_lanes(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_lanes(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_lanes(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_lane = _highest_priority_overdue_retention_breach_lane_scope(scopes)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_lane_counts": (
                    _sum_overdue_retention_breach_lane_counts(scopes)
                ),
                "highest_priority_overdue_retention_breach_lane": (
                    None if highest_lane is None else highest_lane["overdue_retention_breach_lane"]
                ),
                "highest_priority_overdue_retention_breach_lane_priority": (
                    None
                    if highest_lane is None
                    else highest_lane["overdue_retention_breach_lane_priority"]
                ),
                "highest_priority_overdue_retention_breach_lane_scope_kind": (
                    None if highest_lane is None else highest_lane["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_lane_scope_id": (
                    None if highest_lane is None else highest_lane["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_lane_target_memory_id": (
                    None if highest_lane is None else highest_lane["target_memory_id"]
                ),
                "highest_priority_overdue_retention_breach_lane_reasons": (
                    []
                    if highest_lane is None
                    else highest_lane["overdue_retention_breach_lane_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_owner_targets(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_owner_targets(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_owner_targets(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_owner_targets(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_owner_target = _highest_priority_overdue_retention_breach_owner_target_scope(
            scopes
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_owner_target_counts": (
                    _sum_overdue_retention_breach_owner_target_counts(scopes)
                ),
                "highest_priority_overdue_retention_breach_owner_target": (
                    None
                    if highest_owner_target is None
                    else highest_owner_target["overdue_retention_breach_owner_target"]
                ),
                "highest_priority_overdue_retention_breach_owner_target_priority": (
                    None
                    if highest_owner_target is None
                    else highest_owner_target["overdue_retention_breach_owner_target_priority"]
                ),
                "highest_priority_overdue_retention_breach_owner_target_scope_kind": (
                    None
                    if highest_owner_target is None
                    else highest_owner_target["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_owner_target_scope_id": (
                    None
                    if highest_owner_target is None
                    else highest_owner_target["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_owner_target_memory_id": (
                    None
                    if highest_owner_target is None
                    else highest_owner_target["target_memory_id"]
                ),
                "highest_priority_overdue_retention_breach_owner_target_reasons": (
                    []
                    if highest_owner_target is None
                    else highest_owner_target["overdue_retention_breach_owner_target_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_follow_through_modes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_follow_through_modes(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_follow_through_modes(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_follow_through_modes(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_mode = _highest_priority_overdue_retention_breach_follow_through_scope(
            scopes
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_follow_through_counts": (
                    _sum_overdue_retention_breach_follow_through_counts(scopes)
                ),
                "highest_priority_overdue_retention_breach_follow_through_mode": (
                    None
                    if highest_mode is None
                    else highest_mode["overdue_retention_breach_follow_through_mode"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_priority": (
                    None
                    if highest_mode is None
                    else highest_mode["overdue_retention_breach_follow_through_priority"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_scope_kind": (
                    None if highest_mode is None else highest_mode["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_scope_id": (
                    None if highest_mode is None else highest_mode["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_memory_id": (
                    None if highest_mode is None else highest_mode["target_memory_id"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_reasons": (
                    []
                    if highest_mode is None
                    else highest_mode["overdue_retention_breach_follow_through_reasons"]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_follow_through_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_follow_through_outcomes(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_follow_through_outcomes(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_follow_through_outcomes(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_outcome = _highest_priority_overdue_retention_breach_follow_through_outcome_scope(
            scopes
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_follow_through_outcome_counts": (
                    _sum_overdue_retention_breach_follow_through_outcome_counts(scopes)
                ),
                "highest_priority_overdue_retention_breach_follow_through_outcome": (
                    None
                    if highest_outcome is None
                    else highest_outcome[
                        "overdue_retention_breach_follow_through_outcome"
                    ]
                ),
                "highest_priority_overdue_retention_breach_follow_through_outcome_priority": (
                    None
                    if highest_outcome is None
                    else highest_outcome[
                        "overdue_retention_breach_follow_through_outcome_priority"
                    ]
                ),
                "highest_priority_overdue_retention_breach_follow_through_outcome_scope_kind": (
                    None if highest_outcome is None else highest_outcome["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_outcome_scope_id": (
                    None if highest_outcome is None else highest_outcome["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_outcome_memory_id": (
                    None if highest_outcome is None else highest_outcome["target_memory_id"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_outcome_reasons": (
                    []
                    if highest_outcome is None
                    else highest_outcome[
                        "overdue_retention_breach_follow_through_outcome_reasons"
                    ]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_follow_through_completion_states(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_follow_through_completion_states(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_follow_through_completion_states(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_follow_through_completion_states(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_state = _highest_priority_overdue_retention_breach_follow_through_completion_scope(
            scopes
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_follow_through_completion_counts": (
                    _sum_overdue_retention_breach_follow_through_completion_counts(
                        scopes
                    )
                ),
                "highest_priority_overdue_retention_breach_follow_through_completion_state": (
                    None
                    if highest_state is None
                    else highest_state[
                        "overdue_retention_breach_follow_through_completion_state"
                    ]
                ),
                "highest_priority_overdue_retention_breach_follow_through_completion_priority": (
                    None
                    if highest_state is None
                    else highest_state[
                        "overdue_retention_breach_follow_through_completion_priority"
                    ]
                ),
                "highest_priority_overdue_retention_breach_follow_through_completion_scope_kind": (
                    None if highest_state is None else highest_state["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_completion_scope_id": (
                    None if highest_state is None else highest_state["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_completion_memory_id": (
                    None if highest_state is None else highest_state["target_memory_id"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_completion_reasons": (
                    []
                    if highest_state is None
                    else highest_state[
                        "overdue_retention_breach_follow_through_completion_reasons"
                    ]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_follow_through_verification_states(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_follow_through_verification_states(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_follow_through_verification_states(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_follow_through_verification_states(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_state = (
            _highest_priority_overdue_retention_breach_follow_through_verification_scope(
                scopes
            )
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_follow_through_verification_counts": (
                    _sum_overdue_retention_breach_follow_through_verification_counts(
                        scopes
                    )
                ),
                "highest_priority_overdue_retention_breach_follow_through_verification_state": (
                    None
                    if highest_state is None
                    else highest_state[
                        "overdue_retention_breach_follow_through_verification_state"
                    ]
                ),
                "highest_priority_overdue_retention_breach_follow_through_verification_priority": (
                    None
                    if highest_state is None
                    else highest_state[
                        "overdue_retention_breach_follow_through_verification_priority"
                    ]
                ),
                (
                    "highest_priority_overdue_retention_breach_follow_through_"
                    "verification_scope_kind"
                ): (
                    None if highest_state is None else highest_state["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_verification_scope_id": (
                    None if highest_state is None else highest_state["scope_id"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_verification_memory_id": (
                    None if highest_state is None else highest_state["target_memory_id"]
                ),
                "highest_priority_overdue_retention_breach_follow_through_verification_reasons": (
                    []
                    if highest_state is None
                    else highest_state[
                        "overdue_retention_breach_follow_through_verification_reasons"
                    ]
                ),
                "scopes": scopes,
            },
        )

    def get_memory_overdue_retention_breach_follow_through_verification_outcomes(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(SQLiteEventStore(self.database_path).list_for_session(session_key))
        workspace_root = session_workspace_root(events)
        if workspace_root is None:
            return conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session workspace_root is unavailable",
            )
        parsed = parse_memory_overview_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
        scopes: list[dict[str, object]] = [
            {
                "scope_kind": "repo",
                "scope_id": str(workspace_root),
                **read_repo_memory_overdue_retention_breach_follow_through_verification_outcomes(
                    database_path=self.database_path,
                    repo_id=str(workspace_root),
                    as_of=effective_as_of,
                ),
            }
        ]
        if parsed["user_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "user",
                    "scope_id": parsed["user_id"],
                    **read_user_memory_overdue_retention_breach_follow_through_verification_outcomes(
                        database_path=self.database_path,
                        user_id=parsed["user_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        if parsed["tenant_id"] is not None:
            scopes.append(
                {
                    "scope_kind": "tenant",
                    "scope_id": parsed["tenant_id"],
                    **read_tenant_memory_overdue_retention_breach_follow_through_verification_outcomes(
                        database_path=self.database_path,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_outcome = (
            _highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope(
                scopes
            )
        )
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "repo_id": str(workspace_root),
                "user_id": parsed["user_id"],
                "tenant_id": parsed["tenant_id"],
                "reference_at": effective_as_of.isoformat(),
                "scope_count": len(scopes),
                "overdue_scope_count": _sum_overdue_scope_count(scopes),
                "overdue_retention_breach_follow_through_verification_outcome_counts": (
                    _sum_overdue_retention_breach_follow_through_verification_outcome_counts(
                        scopes
                    )
                ),
                "highest_priority_overdue_retention_breach_follow_through_verification_outcome": (
                    None
                    if highest_outcome is None
                    else highest_outcome[
                        "overdue_retention_breach_follow_through_verification_outcome"
                    ]
                ),
                (
                    "highest_priority_overdue_retention_breach_follow_through_"
                    "verification_outcome_priority"
                ): (
                    None
                    if highest_outcome is None
                    else highest_outcome[
                        "overdue_retention_breach_follow_through_verification_outcome_priority"
                    ]
                ),
                (
                    "highest_priority_overdue_retention_breach_follow_through_"
                    "verification_outcome_scope_kind"
                ): (
                    None if highest_outcome is None else highest_outcome["scope_kind"]
                ),
                (
                    "highest_priority_overdue_retention_breach_follow_through_"
                    "verification_outcome_scope_id"
                ): (
                    None if highest_outcome is None else highest_outcome["scope_id"]
                ),
                (
                    "highest_priority_overdue_retention_breach_follow_through_"
                    "verification_outcome_memory_id"
                ): (
                    None if highest_outcome is None else highest_outcome["target_memory_id"]
                ),
                (
                    "highest_priority_overdue_retention_breach_follow_through_"
                    "verification_outcome_reasons"
                ): (
                    []
                    if highest_outcome is None
                    else highest_outcome[
                        "overdue_retention_breach_follow_through_verification_outcome_reasons"
                    ]
                ),
                "scopes": scopes,
            },
        )

    def get_user_memory(self, user_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "user_id": user_id,
                "memories": read_user_memory_inventory(
                    database_path=self.database_path,
                    user_id=user_id,
                ),
            },
        )

    def get_user_memory_queue(self, user_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "user_id": user_id,
                "memories": read_user_memory_queue(
                    database_path=self.database_path,
                    user_id=user_id,
                ),
            },
        )

    def get_user_memory_queue_summary(self, user_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "user_id": user_id,
                **read_user_memory_queue_summary(
                    database_path=self.database_path,
                    user_id=user_id,
                ),
            },
        )

    def get_tenant_memory(self, tenant_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "tenant_id": tenant_id,
                "memories": read_tenant_memory_inventory(
                    database_path=self.database_path,
                    tenant_id=tenant_id,
                ),
            },
        )

    def get_tenant_memory_queue(self, tenant_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "tenant_id": tenant_id,
                "memories": read_tenant_memory_queue(
                    database_path=self.database_path,
                    tenant_id=tenant_id,
                ),
            },
        )

    def get_tenant_memory_queue_summary(self, tenant_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "tenant_id": tenant_id,
                **read_tenant_memory_queue_summary(
                    database_path=self.database_path,
                    tenant_id=tenant_id,
                ),
            },
        )

    def get_session_artifacts(self, session_id: str) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        artifacts = SQLiteArtifactStore(self.database_path).list_for_session(session_key)
        return ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "artifacts": [
                    self._serialize_artifact(artifact)
                    for artifact in artifacts
                ],
            },
        )

    def get_session_artifact_detail(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        access = classify_session_artifact_access(
            self.database_path,
            session_id=session_id,
            artifact=artifact,
        )
        if not access.allowed:
            response = build_artifact_policy_denied_response(
                session_id=session_id,
                status="artifact_access_denied",
                action="read",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.detail",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_access_denied",
                    retrieval_status="access_denied",
                ),
            )
            return response
        projection = self._serialize_artifact(artifact, access=access)
        response = ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "status": "ok",
                "artifact": projection,
            },
        )
        retrieval = projection["retrieval"]
        assert isinstance(retrieval, dict)
        retrieval_status = retrieval["status"]
        assert isinstance(retrieval_status, str)
        record_delivery_audit(
            database_path=self.database_path,
            session_id=session_id,
            action="session.artifact.detail",
            response=response,
            policy_profile=access.session_policy_profile,
            result_metadata=build_artifact_access_metadata(
                access,
                artifact=artifact,
                result_status="ok",
                retrieval_status=retrieval_status,
                extra={
                    "source": artifact.source,
                    "kind": artifact.kind,
                    "preview_redacted": artifact.preview_state["redacted"],
                    "preview_truncated": artifact.preview_state["truncated"],
                },
            ),
        )
        return response

    def get_session_artifact_content(self, session_id: str, artifact_id: str) -> ApiResponse:
        artifact = self._resolve_session_artifact(session_id, artifact_id)
        if isinstance(artifact, ApiResponse):
            return artifact
        access = classify_session_artifact_access(
            self.database_path,
            session_id=session_id,
            artifact=artifact,
        )
        if not access.allowed:
            response = build_artifact_policy_denied_response(
                session_id=session_id,
                status="artifact_access_denied",
                action="read",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_access_denied",
                    retrieval_status="access_denied",
                ),
            )
            return response
        lifecycle = _artifact_lifecycle(self.database_path, artifact.uri)
        retrieval = serialize_artifact_retrieval(
            artifact.uri,
            lifecycle=lifecycle,
        )
        status = str(retrieval["status"])
        if status == "indexed_only":
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_is_indexed_only",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status=status,
                ),
            )
            return response
        if status == "external_reference":
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_uses_external_reference",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status=status,
                ),
            )
            return response
        if status == "payload_missing":
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_payload_missing",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status=status,
                ),
            )
            return response
        if status == "payload_pruned":
            response = build_artifact_unavailable_response(
                session_id=session_id,
                reason="artifact_payload_pruned",
                access=access,
            )
            record_delivery_audit(
                database_path=self.database_path,
                session_id=session_id,
                action="session.artifact.content",
                response=response,
                policy_profile=access.session_policy_profile,
                result_metadata=build_artifact_access_metadata(
                    access,
                    artifact=artifact,
                    result_status="artifact_unavailable",
                    retrieval_status=status,
                ),
            )
            return response
        assert artifact.uri is not None
        payload = Path(urlparse(artifact.uri).path).read_bytes()
        response = ApiResponse(
            status_code=200,
            body={
                "session_id": session_id,
                "artifact_id": artifact.artifact_id,
                "status": "ok",
                "access": serialize_artifact_access(access),
                "encoding": "base64",
                "content_base64": base64.b64encode(payload).decode("ascii"),
                "size_bytes": len(payload),
            },
        )
        record_delivery_audit(
            database_path=self.database_path,
            session_id=session_id,
            action="session.artifact.content",
            response=response,
            policy_profile=access.session_policy_profile,
            result_metadata=build_artifact_access_metadata(
                access,
                artifact=artifact,
                result_status="ok",
                retrieval_status=status,
                extra={"size_bytes": len(payload)},
            ),
        )
        return response

    def get_session_delivery_audit(self, session_id: str) -> ApiResponse:
        return SessionDeliveryAuditApi(self.database_path).get_delivery_audit(session_id)

    def _resolve_session_artifact(
        self,
        session_id: str,
        artifact_id: str,
    ) -> SessionArtifact | ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = SQLiteProjectionStore(self.database_path).get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        artifacts = SQLiteArtifactStore(self.database_path).list_for_session(session_key)
        for artifact in artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        return ApiResponse(
            status_code=404,
            body={
                "session_id": session_id,
                "artifact_id": artifact_id,
                "status": "not_found",
            },
        )

    def _serialize_artifact(
        self,
        artifact: SessionArtifact,
        *,
        access: ArtifactAccessContext | None = None,
    ) -> dict[str, object]:
        resolved_access = access or classify_session_artifact_access(
            self.database_path,
            session_id=str(artifact.session_id),
            artifact=artifact,
        )
        lifecycle = _artifact_lifecycle(self.database_path, artifact.uri)
        projection = serialize_session_artifact_projection(
            artifact,
            lifecycle=lifecycle,
        )
        projection["access"] = serialize_artifact_access(resolved_access)
        return projection


def _artifact_lifecycle(database_path: Path, uri: str | None) -> dict[str, object] | None:
    payload = payload_for_artifact_uri(SQLiteArtifactPayloadStore(database_path), uri)
    return serialize_artifact_lifecycle(payload)


def _sum_pending_counts(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        pending_count = scope.get("pending_count")
        if isinstance(pending_count, int) and not isinstance(pending_count, bool):
            total += pending_count
    return total


def _sum_reviewed_counts(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        reviewed_count = scope.get("reviewed_count")
        if isinstance(reviewed_count, int) and not isinstance(reviewed_count, bool):
            total += reviewed_count
    return total


def _sum_status_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("review_status_counts")
        if not isinstance(counts, dict):
            continue
        for status, count in counts.items():
            if not isinstance(status, str):
                continue
            if not isinstance(count, int) or isinstance(count, bool):
                continue
            totals[status] = totals.get(status, 0) + count
    return totals


def _sum_age_bucket_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals = {
        "lt_1d": 0,
        "gte_1d_lt_3d": 0,
        "gte_3d_lt_7d": 0,
        "gte_7d": 0,
    }
    for scope in scopes:
        buckets = scope.get("pending_age_buckets")
        if not isinstance(buckets, dict):
            continue
        for bucket_name in totals:
            count = buckets.get(bucket_name)
            if isinstance(count, int) and not isinstance(count, bool):
                totals[bucket_name] += count
    return totals


def _sum_recent_review_counts(
    scopes: list[dict[str, object]],
    field_name: str,
) -> int:
    total = 0
    for scope in scopes:
        count = scope.get(field_name)
        if isinstance(count, int) and not isinstance(count, bool):
            total += count
    return total


def _latest_review_scope(
    scopes: list[dict[str, object]],
) -> dict[str, str] | None:
    latest: dict[str, str] | None = None
    for scope in scopes:
        recorded_at = scope.get("latest_reviewed_at")
        status = scope.get("latest_review_status")
        operator = scope.get("latest_review_operator")
        window = scope.get("latest_review_window")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        if not (
            isinstance(recorded_at, str)
            and isinstance(status, str)
            and isinstance(operator, str)
            and isinstance(window, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
        ):
            continue
        candidate = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "recorded_at": recorded_at,
            "status": status,
            "operator": operator,
            "window": window,
        }
        if latest is None or recorded_at > latest["recorded_at"]:
            latest = candidate
    return latest


def _sum_pressure_level_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        level = scope.get("pressure_level")
        if not isinstance(level, str):
            continue
        totals[level] = totals.get(level, 0) + 1
    return totals


def _highest_pressure_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        level = scope.get("pressure_level")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        reasons = scope.get("pressure_reasons")
        if not (
            isinstance(level, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "pressure_level": level,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "pressure_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _pressure_rank(level) > _pressure_rank(
            str(highest["pressure_level"])
        ):
            highest = candidate
    return highest


def _pressure_rank(level: str) -> int:
    ranks = {
        "clear": 0,
        "steady": 1,
        "elevated": 2,
        "high": 3,
    }
    return ranks.get(level, -1)


def _sum_action_hint_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        hint = scope.get("action_hint")
        if not isinstance(hint, str):
            continue
        totals[hint] = totals.get(hint, 0) + 1
    return totals


def _sum_escalation_recommendation_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        recommendation = scope.get("escalation_recommendation")
        if not isinstance(recommendation, str):
            continue
        totals[recommendation] = totals.get(recommendation, 0) + 1
    return totals


def _sum_follow_up_window_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        window = scope.get("follow_up_window")
        if not isinstance(window, str):
            continue
        totals[window] = totals.get(window, 0) + 1
    return totals


def _sum_overdue_scope_count(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        if scope.get("follow_up_overdue") is True:
            total += 1
    return total


def _sum_overdue_age_bucket_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        bucket = scope.get("overdue_age_bucket")
        if not isinstance(bucket, str):
            continue
        totals[bucket] = totals.get(bucket, 0) + 1
    return totals


def _sum_overdue_memory_type_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("overdue_memory_type_counts")
        if not isinstance(counts, dict):
            continue
        for memory_type, count in counts.items():
            if not isinstance(memory_type, str) or not isinstance(count, int):
                continue
            totals[memory_type] = totals.get(memory_type, 0) + count
    return totals


def _sum_overdue_memory_visibility_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("overdue_memory_visibility_counts")
        if not isinstance(counts, dict):
            continue
        for visibility, count in counts.items():
            if not isinstance(visibility, str) or not isinstance(count, int):
                continue
            totals[visibility] = totals.get(visibility, 0) + count
    return totals


def _sum_overdue_trend_signal_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        signal = scope.get("overdue_trend_signal")
        if not isinstance(signal, str):
            continue
        totals[signal] = totals.get(signal, 0) + 1
    return totals


def _sum_overdue_intervention_hint_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        hint = scope.get("overdue_intervention_hint")
        if not isinstance(hint, str):
            continue
        totals[hint] = totals.get(hint, 0) + 1
    return totals


def _sum_overdue_escalation_lane_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        lane = scope.get("overdue_escalation_lane")
        if not isinstance(lane, str):
            continue
        totals[lane] = totals.get(lane, 0) + 1
    return totals


def _sum_overdue_recovery_path_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        path = scope.get("overdue_recovery_path")
        if not isinstance(path, str):
            continue
        totals[path] = totals.get(path, 0) + 1
    return totals


def _sum_overdue_resolution_checkpoint_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        checkpoint = scope.get("overdue_resolution_checkpoint")
        if not isinstance(checkpoint, str):
            continue
        totals[checkpoint] = totals.get(checkpoint, 0) + 1
    return totals


def _sum_overdue_resolution_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get("overdue_resolution_outcome")
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


def _sum_overdue_closure_decision_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        decision = scope.get("overdue_closure_decision")
        if not isinstance(decision, str):
            continue
        totals[decision] = totals.get(decision, 0) + 1
    return totals


def _sum_overdue_archive_recommendation_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        recommendation = scope.get("overdue_archive_recommendation")
        if not isinstance(recommendation, str):
            continue
        totals[recommendation] = totals.get(recommendation, 0) + 1
    return totals


def _sum_overdue_retention_guidance_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        guidance = scope.get("overdue_retention_guidance")
        if not isinstance(guidance, str):
            continue
        totals[guidance] = totals.get(guidance, 0) + 1
    return totals


def _sum_overdue_retention_window_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        window = scope.get("overdue_retention_window")
        if not isinstance(window, str):
            continue
        totals[window] = totals.get(window, 0) + 1
    return totals


def _sum_overdue_retention_breach_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        breach = scope.get("overdue_retention_breach")
        if not isinstance(breach, str):
            continue
        totals[breach] = totals.get(breach, 0) + 1
    return totals


def _sum_overdue_retention_breach_age_bucket_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        bucket = scope.get("overdue_retention_breach_age_bucket")
        if not isinstance(bucket, str):
            continue
        totals[bucket] = totals.get(bucket, 0) + 1
    return totals


def _sum_overdue_retention_breach_action_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        action = scope.get("overdue_retention_breach_action")
        if not isinstance(action, str):
            continue
        totals[action] = totals.get(action, 0) + 1
    return totals


def _sum_overdue_retention_breach_lane_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        lane = scope.get("overdue_retention_breach_lane")
        if not isinstance(lane, str):
            continue
        totals[lane] = totals.get(lane, 0) + 1
    return totals


def _sum_overdue_retention_breach_owner_target_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        owner_target = scope.get("overdue_retention_breach_owner_target")
        if not isinstance(owner_target, str):
            continue
        totals[owner_target] = totals.get(owner_target, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        mode = scope.get("overdue_retention_breach_follow_through_mode")
        if not isinstance(mode, str):
            continue
        totals[mode] = totals.get(mode, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get("overdue_retention_breach_follow_through_outcome")
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_completion_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_completion_state")
        if not isinstance(state, str):
            continue
        totals[state] = totals.get(state, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_verification_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_verification_state")
        if not isinstance(state, str):
            continue
        totals[state] = totals.get(state, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_verification_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome"
        )
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


def _highest_priority_action_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        hint = scope.get("action_hint")
        priority = scope.get("action_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("action_target_memory_id")
        reasons = scope.get("action_reasons")
        if not (
            isinstance(hint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "action_hint": hint,
            "action_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "action_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["action_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_escalation_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        recommendation = scope.get("escalation_recommendation")
        priority = scope.get("escalation_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("escalation_target_memory_id")
        reasons = scope.get("escalation_reasons")
        if not (
            isinstance(recommendation, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "escalation_recommendation": recommendation,
            "escalation_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "escalation_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["escalation_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_follow_up_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        window = scope.get("follow_up_window")
        priority = scope.get("follow_up_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("follow_up_due_at")
        target_memory_id = scope.get("follow_up_target_memory_id")
        reasons = scope.get("follow_up_reasons")
        if not (
            isinstance(window, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "follow_up_window": window,
            "follow_up_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "follow_up_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["follow_up_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        priority = scope.get("follow_up_overdue_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        overdue_since = scope.get("follow_up_overdue_since")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("follow_up_overdue_reasons")
        if not (
            overdue is True
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(overdue_since, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "follow_up_overdue_priority": priority,
            "follow_up_overdue_since": overdue_since,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "follow_up_overdue_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["follow_up_overdue_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_age_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        bucket = scope.get("overdue_age_bucket")
        age_seconds = scope.get("overdue_age_seconds")
        age_days = scope.get("overdue_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("overdue_age_reasons")
        if not (
            overdue is True
            and isinstance(bucket, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_age_bucket": bucket,
            "overdue_age_seconds": age_seconds,
            "overdue_age_days": age_days,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_age_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _overdue_age_bucket_rank(bucket) > _overdue_age_bucket_rank(
            str(highest["overdue_age_bucket"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_type_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        memory_type = scope.get("highest_overdue_memory_type")
        count = scope.get("highest_overdue_memory_type_count")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        target_memory_type = scope.get("overdue_target_memory_type")
        reasons = scope.get("overdue_type_rollup_reasons")
        if not (
            overdue is True
            and isinstance(memory_type, str)
            and isinstance(count, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "highest_overdue_memory_type": memory_type,
            "highest_overdue_memory_type_count": count,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_target_memory_type": (
                target_memory_type if isinstance(target_memory_type, str) else None
            ),
            "overdue_type_rollup_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None:
            highest = candidate
            continue
        highest_count = cast(int, highest["highest_overdue_memory_type_count"])
        highest_type = highest["highest_overdue_memory_type"]
        if count > highest_count or (
            count == highest_count and memory_type < str(highest_type)
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_visibility_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        visibility = scope.get("highest_overdue_memory_visibility")
        count = scope.get("highest_overdue_memory_visibility_count")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        target_memory_visibility = scope.get("overdue_target_memory_visibility")
        reasons = scope.get("overdue_visibility_rollup_reasons")
        if not (
            overdue is True
            and isinstance(visibility, str)
            and isinstance(count, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "highest_overdue_memory_visibility": visibility,
            "highest_overdue_memory_visibility_count": count,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_target_memory_visibility": (
                target_memory_visibility
                if isinstance(target_memory_visibility, str)
                else None
            ),
            "overdue_visibility_rollup_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None:
            highest = candidate
            continue
        highest_count = cast(int, highest["highest_overdue_memory_visibility_count"])
        highest_visibility = highest["highest_overdue_memory_visibility"]
        if count > highest_count or (
            count == highest_count and visibility < str(highest_visibility)
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_trend_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        signal = scope.get("overdue_trend_signal")
        rank = scope.get("overdue_trend_rank")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("overdue_trend_reasons")
        if not (
            overdue is True
            and isinstance(signal, str)
            and isinstance(rank, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_trend_signal": signal,
            "overdue_trend_rank": rank,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_trend_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None:
            highest = candidate
            continue
        highest_rank = cast(int, highest["overdue_trend_rank"])
        highest_signal = highest["overdue_trend_signal"]
        if rank > highest_rank or (rank == highest_rank and signal < str(highest_signal)):
            highest = candidate
    return highest


def _highest_priority_overdue_intervention_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        hint = scope.get("overdue_intervention_hint")
        priority = scope.get("overdue_intervention_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_intervention_target_memory_id")
        reasons = scope.get("overdue_intervention_reasons")
        if not (
            overdue is True
            and isinstance(hint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_intervention_hint": hint,
            "overdue_intervention_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_intervention_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_intervention_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_escalation_lane_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        lane = scope.get("overdue_escalation_lane")
        priority = scope.get("overdue_escalation_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_escalation_target_memory_id")
        reasons = scope.get("overdue_escalation_reasons")
        if not (
            overdue is True
            and isinstance(lane, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_escalation_lane": lane,
            "overdue_escalation_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_escalation_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_escalation_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_recovery_path_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        path = scope.get("overdue_recovery_path")
        priority = scope.get("overdue_recovery_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_recovery_target_memory_id")
        reasons = scope.get("overdue_recovery_reasons")
        if not (
            overdue is True
            and isinstance(path, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_recovery_path": path,
            "overdue_recovery_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_recovery_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_recovery_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_resolution_checkpoint_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        checkpoint = scope.get("overdue_resolution_checkpoint")
        priority = scope.get("overdue_resolution_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_resolution_target_memory_id")
        reasons = scope.get("overdue_resolution_reasons")
        if not (
            overdue is True
            and isinstance(checkpoint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_resolution_checkpoint": checkpoint,
            "overdue_resolution_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_resolution_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_resolution_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_resolution_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        outcome = scope.get("overdue_resolution_outcome")
        priority = scope.get("overdue_resolution_outcome_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_resolution_outcome_target_memory_id")
        reasons = scope.get("overdue_resolution_outcome_reasons")
        if not (
            overdue is True
            and isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_resolution_outcome": outcome,
            "overdue_resolution_outcome_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_resolution_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_resolution_outcome_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_closure_decision_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        decision = scope.get("overdue_closure_decision")
        priority = scope.get("overdue_closure_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_closure_target_memory_id")
        reasons = scope.get("overdue_closure_reasons")
        if not (
            overdue is True
            and isinstance(decision, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_closure_decision": decision,
            "overdue_closure_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_closure_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_closure_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_archive_recommendation_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        recommendation = scope.get("overdue_archive_recommendation")
        priority = scope.get("overdue_archive_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_archive_target_memory_id")
        reasons = scope.get("overdue_archive_reasons")
        if not (
            overdue is True
            and isinstance(recommendation, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_archive_recommendation": recommendation,
            "overdue_archive_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_archive_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_archive_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_guidance_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        guidance = scope.get("overdue_retention_guidance")
        priority = scope.get("overdue_retention_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_target_memory_id")
        bucket = scope.get("overdue_retention_bucket")
        reasons = scope.get("overdue_retention_reasons")
        if not (
            overdue is True
            and isinstance(guidance, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(bucket, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_guidance": guidance,
            "overdue_retention_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_bucket": bucket,
            "overdue_retention_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_window_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        window = scope.get("overdue_retention_window")
        priority = scope.get("overdue_retention_window_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("overdue_retention_window_due_at")
        target_memory_id = scope.get("overdue_retention_window_target_memory_id")
        reasons = scope.get("overdue_retention_window_reasons")
        if not (
            overdue is True
            and isinstance(window, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_window": window,
            "overdue_retention_window_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_window_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_window_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        breach = scope.get("overdue_retention_breach")
        priority = scope.get("overdue_retention_breach_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("overdue_retention_breach_due_at")
        target_memory_id = scope.get("overdue_retention_breach_target_memory_id")
        reasons = scope.get("overdue_retention_breach_reasons")
        if not (
            overdue is True
            and isinstance(breach, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach": breach,
            "overdue_retention_breach_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_breach_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_aging_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        bucket = scope.get("overdue_retention_breach_age_bucket")
        age_seconds = scope.get("overdue_retention_breach_age_seconds")
        age_days = scope.get("overdue_retention_breach_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        reasons = scope.get("overdue_retention_breach_age_reasons")
        if not (
            isinstance(bucket, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_age_bucket": bucket,
            "overdue_retention_breach_age_seconds": age_seconds,
            "overdue_retention_breach_age_days": age_days,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "overdue_retention_breach_age_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_age_bucket_rank(
            bucket
        ) > _overdue_retention_breach_age_bucket_rank(
            str(highest["overdue_retention_breach_age_bucket"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_action_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        action = scope.get("overdue_retention_breach_action")
        priority = scope.get("overdue_retention_breach_action_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_action_target_memory_id")
        reasons = scope.get("overdue_retention_breach_action_reasons")
        if not (
            isinstance(action, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_action": action,
            "overdue_retention_breach_action_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_action_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_action_rank(
            action
        ) > _overdue_retention_breach_action_rank(
            str(highest["overdue_retention_breach_action"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_lane_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        lane = scope.get("overdue_retention_breach_lane")
        priority = scope.get("overdue_retention_breach_lane_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_lane_target_memory_id")
        reasons = scope.get("overdue_retention_breach_lane_reasons")
        if not (
            isinstance(lane, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_lane": lane,
            "overdue_retention_breach_lane_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_lane_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_lane_rank(
            lane
        ) > _overdue_retention_breach_lane_rank(
            str(highest["overdue_retention_breach_lane"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_owner_target_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        owner_target = scope.get("overdue_retention_breach_owner_target")
        priority = scope.get("overdue_retention_breach_owner_target_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_owner_target_memory_id")
        reasons = scope.get("overdue_retention_breach_owner_target_reasons")
        if not (
            isinstance(owner_target, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_owner_target": owner_target,
            "overdue_retention_breach_owner_target_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_owner_target_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_owner_target_rank(
            owner_target
        ) > _overdue_retention_breach_owner_target_rank(
            str(highest["overdue_retention_breach_owner_target"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        mode = scope.get("overdue_retention_breach_follow_through_mode")
        priority = scope.get("overdue_retention_breach_follow_through_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_follow_through_memory_id")
        reasons = scope.get("overdue_retention_breach_follow_through_reasons")
        if not (
            isinstance(mode, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_mode": mode,
            "overdue_retention_breach_follow_through_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_rank(
            mode
        ) > _overdue_retention_breach_follow_through_rank(
            str(highest["overdue_retention_breach_follow_through_mode"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        outcome = scope.get("overdue_retention_breach_follow_through_outcome")
        priority = scope.get("overdue_retention_breach_follow_through_outcome_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_outcome_memory_id"
        )
        reasons = scope.get("overdue_retention_breach_follow_through_outcome_reasons")
        if not (
            isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_outcome": outcome,
            "overdue_retention_breach_follow_through_outcome_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_outcome_rank(
            outcome
        ) > _overdue_retention_breach_follow_through_outcome_rank(
            str(highest["overdue_retention_breach_follow_through_outcome"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_completion_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_completion_state")
        priority = scope.get("overdue_retention_breach_follow_through_completion_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_completion_memory_id"
        )
        reasons = scope.get("overdue_retention_breach_follow_through_completion_reasons")
        if not (
            isinstance(state, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_completion_state": state,
            "overdue_retention_breach_follow_through_completion_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_completion_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_completion_rank(
            state
        ) > _overdue_retention_breach_follow_through_completion_rank(
            str(highest["overdue_retention_breach_follow_through_completion_state"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_verification_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_verification_state")
        priority = scope.get("overdue_retention_breach_follow_through_verification_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_verification_memory_id"
        )
        reasons = scope.get("overdue_retention_breach_follow_through_verification_reasons")
        if not (
            isinstance(state, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_verification_state": state,
            "overdue_retention_breach_follow_through_verification_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_verification_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_verification_rank(
            state
        ) > _overdue_retention_breach_follow_through_verification_rank(
            str(highest["overdue_retention_breach_follow_through_verification_state"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        outcome = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome"
        )
        priority = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome_priority"
        )
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome_memory_id"
        )
        reasons = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome_reasons"
        )
        if not (
            isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_verification_outcome": outcome,
            "overdue_retention_breach_follow_through_verification_outcome_priority": (
                priority
            ),
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_verification_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_verification_outcome_rank(
            outcome
        ) > _overdue_retention_breach_follow_through_verification_outcome_rank(
            str(highest["overdue_retention_breach_follow_through_verification_outcome"])
        ):
            highest = candidate
    return highest


def _action_priority_rank(priority: str) -> int:
    ranks = {
        "none": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
    }
    return ranks.get(priority, -1)


def _overdue_age_bucket_rank(bucket: str) -> int:
    ranks = {
        "not_overdue": 0,
        "unknown_overdue_age": 0,
        "lt_1d_overdue": 1,
        "gte_1d_lt_3d_overdue": 2,
        "gte_3d_lt_7d_overdue": 3,
        "gte_7d_overdue": 4,
    }
    return ranks.get(bucket, -1)


def _overdue_retention_breach_age_bucket_rank(bucket: str) -> int:
    ranks = {
        "not_breached": 0,
        "unknown_breach_age": 0,
        "lt_1d_breached": 1,
        "gte_1d_lt_3d_breached": 2,
        "gte_3d_lt_7d_breached": 3,
        "gte_7d_breached": 4,
    }
    return ranks.get(bucket, -1)


def _overdue_retention_breach_action_rank(action: str) -> int:
    ranks = {
        "no_retention_action": 0,
        "inspect_breach_timestamps": 1,
        "queue_immediate_retention_review": 2,
        "assign_retention_owner": 3,
        "escalate_retention_decision": 4,
        "force_archive_or_override": 5,
    }
    return ranks.get(action, -1)


def _overdue_retention_breach_lane_rank(lane: str) -> int:
    ranks = {
        "no_retention_lane": 0,
        "operator_timestamp_review_lane": 1,
        "operator_retention_review_lane": 2,
        "owner_assignment_lane": 3,
        "manager_retention_escalation_lane": 4,
        "emergency_retention_override_lane": 5,
    }
    return ranks.get(lane, -1)


def _overdue_retention_breach_owner_target_rank(owner_target: str) -> int:
    ranks = {
        "no_owner_assignment": 0,
        "memory_operator": 1,
        "scope_owner": 2,
        "retention_manager": 3,
        "retention_admin": 4,
    }
    return ranks.get(owner_target, -1)


def _overdue_retention_breach_follow_through_rank(mode: str) -> int:
    ranks = {
        "no_follow_through_needed": 0,
        "operator_review_follow_through": 1,
        "owner_confirmation_follow_through": 2,
        "manager_decision_follow_through": 3,
        "admin_override_follow_through": 4,
    }
    return ranks.get(mode, -1)


def _overdue_retention_breach_follow_through_outcome_rank(outcome: str) -> int:
    ranks = {
        "no_follow_through_outstanding": 0,
        "follow_through_monitoring_only": 1,
        "awaiting_operator_follow_through": 2,
        "awaiting_owner_follow_through": 3,
        "awaiting_manager_follow_through": 4,
        "awaiting_admin_override_follow_through": 5,
    }
    return ranks.get(outcome, -1)


def _overdue_retention_breach_follow_through_completion_rank(state: str) -> int:
    ranks = {
        "completion_not_required": 0,
        "completion_monitoring_only": 1,
        "operator_completion_pending": 2,
        "owner_completion_pending": 3,
        "manager_completion_pending": 4,
        "admin_override_completion_pending": 5,
    }
    return ranks.get(state, -1)


def _overdue_retention_breach_follow_through_verification_rank(state: str) -> int:
    ranks = {
        "verification_not_required": 0,
        "verification_monitoring_only": 1,
        "operator_verification_pending": 2,
        "owner_verification_pending": 3,
        "manager_verification_pending": 4,
        "admin_override_verification_pending": 5,
    }
    return ranks.get(state, -1)


def _overdue_retention_breach_follow_through_verification_outcome_rank(
    outcome: str,
) -> int:
    ranks = {
        "verification_resolved": 0,
        "verification_monitoring_only": 1,
        "awaiting_operator_verification_outcome": 2,
        "awaiting_owner_verification_outcome": 3,
        "awaiting_manager_verification_outcome": 4,
        "awaiting_admin_override_verification_outcome": 5,
    }
    return ranks.get(outcome, -1)


def _oldest_pending_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    oldest: dict[str, object] | None = None
    for scope in scopes:
        captured_at = scope.get("oldest_pending_captured_at")
        memory_id = scope.get("oldest_pending_memory_id")
        age_seconds = scope.get("oldest_pending_age_seconds")
        age_days = scope.get("oldest_pending_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        if not (
            isinstance(captured_at, str)
            and isinstance(memory_id, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
        ):
            continue
        candidate = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "memory_id": memory_id,
            "captured_at": captured_at,
            "age_seconds": age_seconds,
            "age_days": age_days,
        }
        if oldest is None or captured_at < str(oldest["captured_at"]):
            oldest = candidate
    return oldest
