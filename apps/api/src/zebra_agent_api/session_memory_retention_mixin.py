from __future__ import annotations

from pathlib import Path

from agent_storage import ControlPlaneStores

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breach_aging,
    read_repo_memory_overdue_retention_breaches,
    read_repo_memory_overdue_retention_guidance,
    read_repo_memory_overdue_retention_windows,
    read_tenant_memory_overdue_retention_breach_aging,
    read_tenant_memory_overdue_retention_breaches,
    read_tenant_memory_overdue_retention_guidance,
    read_tenant_memory_overdue_retention_windows,
    read_user_memory_overdue_retention_breach_aging,
    read_user_memory_overdue_retention_breaches,
    read_user_memory_overdue_retention_guidance,
    read_user_memory_overdue_retention_windows,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_overview_aggregation import (
    _sum_overdue_scope_count,
)
from zebra_agent_api.session_memory_resolution_priority_read import (
    _highest_priority_overdue_retention_guidance_scope,
)
from zebra_agent_api.session_memory_retention_aggregation import (
    _sum_overdue_retention_breach_age_bucket_counts,
    _sum_overdue_retention_breach_counts,
    _sum_overdue_retention_guidance_counts,
    _sum_overdue_retention_window_counts,
)
from zebra_agent_api.session_memory_retention_priority_read import (
    _highest_priority_overdue_retention_breach_aging_scope,
    _highest_priority_overdue_retention_breach_scope,
    _highest_priority_overdue_retention_window_scope,
)
from zebra_agent_api.session_payloads import parse_memory_overview_payload


class SessionMemoryRetentionMixin:
    database_path: Path
    stores: ControlPlaneStores

    def get_memory_overdue_retention_guidance(
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
                **read_repo_memory_overdue_retention_guidance(
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
                    **read_user_memory_overdue_retention_guidance(
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
                    **read_tenant_memory_overdue_retention_guidance(
                        database_path=self.database_path,
                        stores=self.stores,
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
                "overdue_retention_guidance_counts": _sum_overdue_retention_guidance_counts(scopes),
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
                    None if highest_guidance is None else highest_guidance["target_memory_id"]
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
                **read_repo_memory_overdue_retention_windows(
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
                    **read_user_memory_overdue_retention_windows(
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
                    **read_tenant_memory_overdue_retention_windows(
                        database_path=self.database_path,
                        stores=self.stores,
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
                "overdue_retention_window_counts": _sum_overdue_retention_window_counts(scopes),
                "highest_priority_overdue_retention_window": (
                    None if highest_window is None else highest_window["overdue_retention_window"]
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
                    None if highest_window is None else highest_window["target_memory_id"]
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
                **read_repo_memory_overdue_retention_breaches(
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
                    **read_user_memory_overdue_retention_breaches(
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
                    **read_tenant_memory_overdue_retention_breaches(
                        database_path=self.database_path,
                        stores=self.stores,
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
                "overdue_retention_breach_counts": _sum_overdue_retention_breach_counts(scopes),
                "highest_priority_overdue_retention_breach": (
                    None if highest_breach is None else highest_breach["overdue_retention_breach"]
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
                    None if highest_breach is None else highest_breach["target_memory_id"]
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
                **read_repo_memory_overdue_retention_breach_aging(
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
                    **read_user_memory_overdue_retention_breach_aging(
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
                    **read_tenant_memory_overdue_retention_breach_aging(
                        database_path=self.database_path,
                        stores=self.stores,
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
