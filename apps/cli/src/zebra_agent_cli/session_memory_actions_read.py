from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_escalation_follow_up_windows as read_repo_follow_up_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_pressure_action_hints as read_repo_action_hints,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_pressure_escalation_recommendations as read_repo_escalations,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_escalation_follow_up_windows as read_tenant_follow_up_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_pressure_action_hints as read_tenant_action_hints,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_pressure_escalation_recommendations as read_tenant_escalations,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_escalation_follow_up_windows as read_user_follow_up_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_pressure_action_hints as read_user_action_hints,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_pressure_escalation_recommendations as read_user_escalations,
)

from zebra_agent_cli.session_memory_counting import (
    _session_workspace_root,
    _sum_action_hint_counts,
    _sum_escalation_recommendation_counts,
    _sum_follow_up_window_counts,
)
from zebra_agent_cli.session_memory_priority_read import (
    _highest_priority_action_scope,
    _highest_priority_escalation_scope,
    _highest_priority_follow_up_scope,
)
from zebra_agent_cli.session_memory_ranking import (
    _parse_as_of,
)


def read_session_memory_action_hints(
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
            **read_repo_action_hints(
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
                **read_user_action_hints(
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
                **read_tenant_action_hints(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_action = _highest_priority_action_scope(scopes)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
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
    }


def read_session_memory_escalations(
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
            **read_repo_escalations(
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
                **read_user_escalations(
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
                **read_tenant_escalations(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_escalation = _highest_priority_escalation_scope(scopes)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "reference_at": effective_as_of.isoformat(),
        "scope_count": len(scopes),
        "escalation_recommendation_counts": _sum_escalation_recommendation_counts(scopes),
        "highest_priority_escalation_recommendation": (
            None if highest_escalation is None else highest_escalation["escalation_recommendation"]
        ),
        "highest_priority_escalation_priority": (
            None if highest_escalation is None else highest_escalation["escalation_priority"]
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
    }


def read_session_memory_follow_up_windows(
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
            **read_repo_follow_up_windows(
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
                **read_user_follow_up_windows(
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
                **read_tenant_follow_up_windows(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_follow_up = _highest_priority_follow_up_scope(scopes)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
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
    }
