from __future__ import annotations

from pathlib import Path

from agent_storage import SQLiteEventStore, SQLiteProjectionStore

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_archive_recommendations,
    read_repo_memory_overdue_closure_decisions,
    read_repo_memory_overdue_resolution_checkpoints,
    read_repo_memory_overdue_resolution_outcomes,
    read_tenant_memory_overdue_archive_recommendations,
    read_tenant_memory_overdue_closure_decisions,
    read_tenant_memory_overdue_resolution_checkpoints,
    read_tenant_memory_overdue_resolution_outcomes,
    read_user_memory_overdue_archive_recommendations,
    read_user_memory_overdue_closure_decisions,
    read_user_memory_overdue_resolution_checkpoints,
    read_user_memory_overdue_resolution_outcomes,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_overview_aggregation import (
    _sum_overdue_resolution_checkpoint_counts,
    _sum_overdue_resolution_outcome_counts,
    _sum_overdue_scope_count,
)
from zebra_agent_api.session_memory_resolution_priority_read import (
    _highest_priority_overdue_archive_recommendation_scope,
    _highest_priority_overdue_closure_decision_scope,
    _highest_priority_overdue_resolution_checkpoint_scope,
    _highest_priority_overdue_resolution_outcome_scope,
)
from zebra_agent_api.session_memory_retention_aggregation import (
    _sum_overdue_archive_recommendation_counts,
    _sum_overdue_closure_decision_counts,
)
from zebra_agent_api.session_payloads import parse_memory_overview_payload


class SessionMemoryResolutionMixin:
    database_path: Path

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
                    None if highest_checkpoint is None else highest_checkpoint["scope_kind"]
                ),
                "highest_priority_overdue_resolution_scope_id": (
                    None if highest_checkpoint is None else highest_checkpoint["scope_id"]
                ),
                "highest_priority_overdue_resolution_target_memory_id": (
                    None if highest_checkpoint is None else highest_checkpoint["target_memory_id"]
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
                "overdue_resolution_outcome_counts": _sum_overdue_resolution_outcome_counts(scopes),
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
                "overdue_closure_decision_counts": _sum_overdue_closure_decision_counts(scopes),
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
                    [] if highest_decision is None else highest_decision["overdue_closure_reasons"]
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
        highest_recommendation = _highest_priority_overdue_archive_recommendation_scope(scopes)
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
                    None if highest_recommendation is None else highest_recommendation["scope_kind"]
                ),
                "highest_priority_overdue_archive_scope_id": (
                    None if highest_recommendation is None else highest_recommendation["scope_id"]
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
