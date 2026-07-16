from __future__ import annotations

from pathlib import Path

from agent_storage import SQLiteEventStore, SQLiteProjectionStore

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_follow_up_overdue_flags,
    read_repo_memory_overdue_age_buckets,
    read_repo_memory_overdue_type_rollups,
    read_repo_memory_overdue_visibility_rollups,
    read_tenant_memory_follow_up_overdue_flags,
    read_tenant_memory_overdue_age_buckets,
    read_tenant_memory_overdue_type_rollups,
    read_tenant_memory_overdue_visibility_rollups,
    read_user_memory_follow_up_overdue_flags,
    read_user_memory_overdue_age_buckets,
    read_user_memory_overdue_type_rollups,
    read_user_memory_overdue_visibility_rollups,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_overview_aggregation import (
    _sum_overdue_age_bucket_counts,
    _sum_overdue_memory_type_counts,
    _sum_overdue_memory_visibility_counts,
    _sum_overdue_scope_count,
)
from zebra_agent_api.session_memory_priority_read import (
    _highest_priority_overdue_age_scope,
    _highest_priority_overdue_scope,
    _highest_priority_overdue_type_scope,
    _highest_priority_overdue_visibility_scope,
)
from zebra_agent_api.session_payloads import parse_memory_overview_payload


class SessionMemoryOverdueStatusMixin:
    database_path: Path

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
                    None if highest_overdue is None else highest_overdue["follow_up_overdue_since"]
                ),
                "highest_priority_overdue_target_memory_id": (
                    None if highest_overdue is None else highest_overdue["target_memory_id"]
                ),
                "highest_priority_overdue_reasons": (
                    [] if highest_overdue is None else highest_overdue["follow_up_overdue_reasons"]
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
                    None if highest_overdue_age is None else highest_overdue_age["scope_kind"]
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
                    None if highest_overdue_age is None else highest_overdue_age["overdue_age_days"]
                ),
                "highest_priority_overdue_age_target_memory_id": (
                    None if highest_overdue_age is None else highest_overdue_age["target_memory_id"]
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
                "overdue_memory_visibility_counts": _sum_overdue_memory_visibility_counts(scopes),
                "highest_priority_overdue_memory_visibility": (
                    None
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility["highest_overdue_memory_visibility"]
                ),
                "highest_priority_overdue_memory_visibility_count": (
                    None
                    if highest_overdue_visibility is None
                    else highest_overdue_visibility["highest_overdue_memory_visibility_count"]
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
