from __future__ import annotations

from pathlib import Path

from agent_storage import ControlPlaneStores

from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_repo_memory_overdue_retention_breach_follow_through_verification_states,
    read_tenant_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_tenant_memory_overdue_retention_breach_follow_through_verification_states,
    read_user_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_user_memory_overdue_retention_breach_follow_through_verification_states,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import _parse_session_id
from zebra_agent_api.session_memory_follow_through_priority_read import (
    _highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope,
    _highest_priority_overdue_retention_breach_follow_through_verification_scope,
)
from zebra_agent_api.session_memory_overview_aggregation import _sum_overdue_scope_count
from zebra_agent_api.session_memory_retention_aggregation import (
    _sum_overdue_retention_breach_follow_through_verification_counts,
    _sum_overdue_retention_breach_follow_through_verification_outcome_counts,
)
from zebra_agent_api.session_payloads import parse_memory_overview_payload


class SessionMemoryFollowThroughVerificationMixin:
    database_path: Path
    stores: ControlPlaneStores

    def get_memory_overdue_retention_breach_follow_through_verification_states(
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
                **read_repo_memory_overdue_retention_breach_follow_through_verification_states(
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
                    **read_user_memory_overdue_retention_breach_follow_through_verification_states(
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
                    **read_tenant_memory_overdue_retention_breach_follow_through_verification_states(
                        database_path=self.database_path,
                        stores=self.stores,
                        tenant_id=parsed["tenant_id"],
                        as_of=effective_as_of,
                    ),
                }
            )
        highest_state = (
            _highest_priority_overdue_retention_breach_follow_through_verification_scope(scopes)
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
                    _sum_overdue_retention_breach_follow_through_verification_counts(scopes)
                ),
                "highest_priority_overdue_retention_breach_follow_through_verification_state": (
                    None
                    if highest_state is None
                    else highest_state["overdue_retention_breach_follow_through_verification_state"]
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
                ): (None if highest_state is None else highest_state["scope_kind"]),
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
                **read_repo_memory_overdue_retention_breach_follow_through_verification_outcomes(
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
                    **read_user_memory_overdue_retention_breach_follow_through_verification_outcomes(
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
                    **read_tenant_memory_overdue_retention_breach_follow_through_verification_outcomes(
                        database_path=self.database_path,
                        stores=self.stores,
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
                    _sum_overdue_retention_breach_follow_through_verification_outcome_counts(scopes)
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
                ): (None if highest_outcome is None else highest_outcome["scope_kind"]),
                (
                    "highest_priority_overdue_retention_breach_follow_through_"
                    "verification_outcome_scope_id"
                ): (None if highest_outcome is None else highest_outcome["scope_id"]),
                (
                    "highest_priority_overdue_retention_breach_follow_through_"
                    "verification_outcome_memory_id"
                ): (None if highest_outcome is None else highest_outcome["target_memory_id"]),
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
