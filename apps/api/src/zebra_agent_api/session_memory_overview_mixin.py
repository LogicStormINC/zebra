from __future__ import annotations

from pathlib import Path

from agent_storage import SQLiteEventStore, SQLiteProjectionStore

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_backlog_aging_signals,
    read_repo_memory_governance_signals,
    read_repo_memory_queue_summary,
    read_repo_memory_review_velocity_signals,
    read_tenant_memory_backlog_aging_signals,
    read_tenant_memory_governance_signals,
    read_tenant_memory_queue_summary,
    read_tenant_memory_review_velocity_signals,
    read_user_memory_backlog_aging_signals,
    read_user_memory_governance_signals,
    read_user_memory_queue_summary,
    read_user_memory_review_velocity_signals,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_overview_aggregation import (
    _latest_review_scope,
    _sum_age_bucket_counts,
    _sum_pending_counts,
    _sum_recent_review_counts,
    _sum_reviewed_counts,
    _sum_status_counts,
)
from zebra_agent_api.session_memory_ranking import (
    _oldest_pending_scope,
)
from zebra_agent_api.session_payloads import parse_memory_overview_payload


class SessionMemoryOverviewMixin:
    database_path: Path

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
        effective_as_of = parsed["as_of"] or max(event.created_at for event in events)
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
