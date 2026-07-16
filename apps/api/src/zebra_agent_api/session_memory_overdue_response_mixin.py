from __future__ import annotations

from pathlib import Path

from agent_storage import SQLiteEventStore, SQLiteProjectionStore

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_escalation_lanes,
    read_repo_memory_overdue_intervention_hints,
    read_repo_memory_overdue_recovery_paths,
    read_repo_memory_overdue_trend_signals,
    read_tenant_memory_overdue_escalation_lanes,
    read_tenant_memory_overdue_intervention_hints,
    read_tenant_memory_overdue_recovery_paths,
    read_tenant_memory_overdue_trend_signals,
    read_user_memory_overdue_escalation_lanes,
    read_user_memory_overdue_intervention_hints,
    read_user_memory_overdue_recovery_paths,
    read_user_memory_overdue_trend_signals,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_overview_aggregation import (
    _sum_overdue_escalation_lane_counts,
    _sum_overdue_intervention_hint_counts,
    _sum_overdue_recovery_path_counts,
    _sum_overdue_scope_count,
    _sum_overdue_trend_signal_counts,
)
from zebra_agent_api.session_memory_priority_read import (
    _highest_priority_overdue_intervention_scope,
    _highest_priority_overdue_trend_scope,
)
from zebra_agent_api.session_memory_resolution_priority_read import (
    _highest_priority_overdue_escalation_lane_scope,
    _highest_priority_overdue_recovery_path_scope,
)
from zebra_agent_api.session_payloads import parse_memory_overview_payload


class SessionMemoryOverdueResponseMixin:
    database_path: Path

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
                "overdue_intervention_hint_counts": _sum_overdue_intervention_hint_counts(scopes),
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
                "overdue_escalation_lane_counts": _sum_overdue_escalation_lane_counts(scopes),
                "highest_priority_overdue_escalation_lane": (
                    None if highest_lane is None else highest_lane["overdue_escalation_lane"]
                ),
                "highest_priority_overdue_escalation_priority": (
                    None if highest_lane is None else highest_lane["overdue_escalation_priority"]
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
                    [] if highest_lane is None else highest_lane["overdue_escalation_reasons"]
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
                    None if highest_recovery is None else highest_recovery["overdue_recovery_path"]
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
                    [] if highest_recovery is None else highest_recovery["overdue_recovery_reasons"]
                ),
                "scopes": scopes,
            },
        )
