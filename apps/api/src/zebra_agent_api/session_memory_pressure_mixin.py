from __future__ import annotations

from pathlib import Path

from agent_storage import ControlPlaneStores

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_backlog_pressure_signals,
    read_repo_memory_escalation_follow_up_windows,
    read_repo_memory_pressure_action_hints,
    read_repo_memory_pressure_escalation_recommendations,
    read_tenant_memory_backlog_pressure_signals,
    read_tenant_memory_escalation_follow_up_windows,
    read_tenant_memory_pressure_action_hints,
    read_tenant_memory_pressure_escalation_recommendations,
    read_user_memory_backlog_pressure_signals,
    read_user_memory_escalation_follow_up_windows,
    read_user_memory_pressure_action_hints,
    read_user_memory_pressure_escalation_recommendations,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_overview_aggregation import (
    _highest_pressure_scope,
    _sum_action_hint_counts,
    _sum_age_bucket_counts,
    _sum_escalation_recommendation_counts,
    _sum_follow_up_window_counts,
    _sum_pending_counts,
    _sum_pressure_level_counts,
    _sum_recent_review_counts,
)
from zebra_agent_api.session_memory_priority_read import (
    _highest_priority_action_scope,
    _highest_priority_escalation_scope,
    _highest_priority_follow_up_scope,
)
from zebra_agent_api.session_payloads import parse_memory_overview_payload


class SessionMemoryPressureMixin:
    database_path: Path
    stores: ControlPlaneStores

    def get_memory_backlog_pressure_signals(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        session_key = _parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(self.stores.events.list_for_session(session_key))
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
                    stores=self.stores,
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
                        stores=self.stores,
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
                        stores=self.stores,
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
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(self.stores.events.list_for_session(session_key))
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
                    stores=self.stores,
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
                        stores=self.stores,
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
                        stores=self.stores,
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
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(self.stores.events.list_for_session(session_key))
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
                    stores=self.stores,
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
                        stores=self.stores,
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
                        stores=self.stores,
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
                "escalation_recommendation_counts": _sum_escalation_recommendation_counts(scopes),
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
                    None if highest_escalation is None else highest_escalation["target_memory_id"]
                ),
                "highest_priority_escalation_reasons": (
                    [] if highest_escalation is None else highest_escalation["escalation_reasons"]
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
        session = self.stores.sessions.get_session(session_key)
        if session is None:
            return ApiResponse(
                status_code=404,
                body={"session_id": session_id, "status": "not_found"},
            )
        events = list(self.stores.events.list_for_session(session_key))
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
                    stores=self.stores,
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
                        stores=self.stores,
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
                        stores=self.stores,
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
                    None if highest_follow_up is None else highest_follow_up["follow_up_priority"]
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
                    None if highest_follow_up is None else highest_follow_up["target_memory_id"]
                ),
                "highest_priority_follow_up_reasons": (
                    [] if highest_follow_up is None else highest_follow_up["follow_up_reasons"]
                ),
                "scopes": scopes,
            },
        )
