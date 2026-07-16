from __future__ import annotations

from pathlib import Path

from agent_storage import SQLiteEventStore, SQLiteProjectionStore

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breach_actions,
    read_repo_memory_overdue_retention_breach_follow_through_modes,
    read_repo_memory_overdue_retention_breach_lanes,
    read_repo_memory_overdue_retention_breach_owner_targets,
    read_tenant_memory_overdue_retention_breach_actions,
    read_tenant_memory_overdue_retention_breach_follow_through_modes,
    read_tenant_memory_overdue_retention_breach_lanes,
    read_tenant_memory_overdue_retention_breach_owner_targets,
    read_user_memory_overdue_retention_breach_actions,
    read_user_memory_overdue_retention_breach_follow_through_modes,
    read_user_memory_overdue_retention_breach_lanes,
    read_user_memory_overdue_retention_breach_owner_targets,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_follow_through_priority_read import (
    _highest_priority_overdue_retention_breach_follow_through_scope,
)
from zebra_agent_api.session_memory_overview_aggregation import (
    _sum_overdue_scope_count,
)
from zebra_agent_api.session_memory_retention_aggregation import (
    _sum_overdue_retention_breach_action_counts,
    _sum_overdue_retention_breach_follow_through_counts,
    _sum_overdue_retention_breach_lane_counts,
    _sum_overdue_retention_breach_owner_target_counts,
)
from zebra_agent_api.session_memory_retention_priority_read import (
    _highest_priority_overdue_retention_breach_action_scope,
    _highest_priority_overdue_retention_breach_lane_scope,
    _highest_priority_overdue_retention_breach_owner_target_scope,
)
from zebra_agent_api.session_payloads import parse_memory_overview_payload


class SessionMemoryBreachMixin:
    database_path: Path

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
                    None if highest_action is None else highest_action["target_memory_id"]
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
        highest_owner_target = _highest_priority_overdue_retention_breach_owner_target_scope(scopes)
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
                    None if highest_owner_target is None else highest_owner_target["scope_kind"]
                ),
                "highest_priority_overdue_retention_breach_owner_target_scope_id": (
                    None if highest_owner_target is None else highest_owner_target["scope_id"]
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
        highest_mode = _highest_priority_overdue_retention_breach_follow_through_scope(scopes)
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
