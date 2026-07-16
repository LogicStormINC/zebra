from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breach_follow_through_completion_states,
    read_tenant_memory_overdue_retention_breach_follow_through_completion_states,
    read_user_memory_overdue_retention_breach_follow_through_completion_states,
)

from zebra_agent_cli.session_memory_counting import (
    _session_workspace_root,
    _sum_overdue_retention_breach_follow_through_completion_counts,
    _sum_overdue_scope_count,
)
from zebra_agent_cli.session_memory_follow_through_priority_read import (
    _highest_priority_overdue_retention_breach_follow_through_completion_scope,
)
from zebra_agent_cli.session_memory_ranking import (
    _parse_as_of,
)

read_repo_follow_through_completion_states = (
    read_repo_memory_overdue_retention_breach_follow_through_completion_states
)

read_tenant_follow_through_completion_states = (
    read_tenant_memory_overdue_retention_breach_follow_through_completion_states
)

read_user_follow_through_completion_states = (
    read_user_memory_overdue_retention_breach_follow_through_completion_states
)


def read_session_memory_overdue_retention_breach_follow_through_completion_states(
    *,
    database_path: Path,
    session_id: str,
    user_id: str | None,
    tenant_id: str | None,
    as_of: str | None,
) -> dict[str, object]:
    session_key = SessionId(UUID(session_id))
    session = SQLiteProjectionStore(database_path).get_session(session_key)
    if session is None:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "not_found",
        }
    events = list(SQLiteEventStore(database_path).list_for_session(session_key))
    workspace_root = _session_workspace_root(events)
    if workspace_root is None:
        return {
            "session_id": session_id,
            "database": str(database_path),
            "status": "memory_unavailable",
            "reason": "session workspace_root is unavailable",
        }
    parsed_as_of = _parse_as_of(as_of)
    if isinstance(parsed_as_of, dict):
        return {
            "session_id": session_id,
            "database": str(database_path),
            **parsed_as_of,
        }
    effective_as_of = parsed_as_of or max(event.created_at for event in events)
    scopes: list[dict[str, object]] = [
        {
            "scope_kind": "repo",
            "scope_id": str(workspace_root),
            **read_repo_follow_through_completion_states(
                database_path=database_path,
                repo_id=str(workspace_root),
                as_of=effective_as_of,
            ),
        }
    ]
    if user_id is not None:
        scopes.append(
            {
                "scope_kind": "user",
                "scope_id": user_id,
                **read_user_follow_through_completion_states(
                    database_path=database_path,
                    user_id=user_id,
                    as_of=effective_as_of,
                ),
            }
        )
    if tenant_id is not None:
        scopes.append(
            {
                "scope_kind": "tenant",
                "scope_id": tenant_id,
                **read_tenant_follow_through_completion_states(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_state = _highest_priority_overdue_retention_breach_follow_through_completion_scope(
        scopes
    )
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "reference_at": effective_as_of.isoformat(),
        "scope_count": len(scopes),
        "overdue_scope_count": _sum_overdue_scope_count(scopes),
        "overdue_retention_breach_follow_through_completion_counts": (
            _sum_overdue_retention_breach_follow_through_completion_counts(scopes)
        ),
        "highest_priority_overdue_retention_breach_follow_through_completion_state": (
            None
            if highest_state is None
            else highest_state["overdue_retention_breach_follow_through_completion_state"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_completion_priority": (
            None
            if highest_state is None
            else highest_state["overdue_retention_breach_follow_through_completion_priority"]
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
            else highest_state["overdue_retention_breach_follow_through_completion_reasons"]
        ),
        "scopes": scopes,
    }
