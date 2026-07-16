from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_intervention_hints as read_repo_overdue_interventions,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_trend_signals as read_repo_overdue_trends,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_visibility_rollups as read_repo_overdue_visibility,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_intervention_hints as read_tenant_overdue_interventions,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_trend_signals as read_tenant_overdue_trends,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_visibility_rollups as read_tenant_overdue_visibility,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_intervention_hints as read_user_overdue_interventions,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_trend_signals as read_user_overdue_trends,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_visibility_rollups as read_user_overdue_visibility,
)

from zebra_agent_cli.session_memory_counting import (
    _session_workspace_root,
    _sum_overdue_intervention_hint_counts,
    _sum_overdue_memory_visibility_counts,
    _sum_overdue_scope_count,
    _sum_overdue_trend_signal_counts,
)
from zebra_agent_cli.session_memory_priority_read import (
    _highest_priority_overdue_visibility_scope,
)
from zebra_agent_cli.session_memory_ranking import (
    _parse_as_of,
)
from zebra_agent_cli.session_memory_resolution_priority_read import (
    _highest_priority_overdue_intervention_scope,
    _highest_priority_overdue_trend_scope,
)


def read_session_memory_overdue_visibility_rollups(
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
            **read_repo_overdue_visibility(
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
                **read_user_overdue_visibility(
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
                **read_tenant_overdue_visibility(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_overdue_visibility = _highest_priority_overdue_visibility_scope(scopes)
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
            None if highest_overdue_visibility is None else highest_overdue_visibility["scope_kind"]
        ),
        "highest_priority_overdue_visibility_scope_id": (
            None if highest_overdue_visibility is None else highest_overdue_visibility["scope_id"]
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
    }


def read_session_memory_overdue_trend_signals(
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
            **read_repo_overdue_trends(
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
                **read_user_overdue_trends(
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
                **read_tenant_overdue_trends(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_overdue_trend = _highest_priority_overdue_trend_scope(scopes)
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
        "overdue_trend_signal_counts": _sum_overdue_trend_signal_counts(scopes),
        "highest_priority_overdue_trend_signal": (
            None if highest_overdue_trend is None else highest_overdue_trend["overdue_trend_signal"]
        ),
        "highest_priority_overdue_trend_rank": (
            None if highest_overdue_trend is None else highest_overdue_trend["overdue_trend_rank"]
        ),
        "highest_priority_overdue_trend_scope_kind": (
            None if highest_overdue_trend is None else highest_overdue_trend["scope_kind"]
        ),
        "highest_priority_overdue_trend_scope_id": (
            None if highest_overdue_trend is None else highest_overdue_trend["scope_id"]
        ),
        "highest_priority_overdue_trend_target_memory_id": (
            None if highest_overdue_trend is None else highest_overdue_trend["target_memory_id"]
        ),
        "highest_priority_overdue_trend_reasons": (
            [] if highest_overdue_trend is None else highest_overdue_trend["overdue_trend_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_intervention_hints(
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
            **read_repo_overdue_interventions(
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
                **read_user_overdue_interventions(
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
                **read_tenant_overdue_interventions(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_intervention = _highest_priority_overdue_intervention_scope(scopes)
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
            None if highest_intervention is None else highest_intervention["target_memory_id"]
        ),
        "highest_priority_overdue_intervention_reasons": (
            []
            if highest_intervention is None
            else highest_intervention["overdue_intervention_reasons"]
        ),
        "scopes": scopes,
    }
