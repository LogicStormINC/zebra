from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_archive_recommendations as read_repo_overdue_archive_recommendations,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breaches as read_repo_overdue_retention_breaches,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_guidance as read_repo_overdue_retention_guidance,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_windows as read_repo_overdue_retention_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_archive_recommendations as read_tenant_archive_recommendations,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_breaches as read_tenant_retention_breaches,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_guidance as read_tenant_retention_guidance,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_windows as read_tenant_retention_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_archive_recommendations as read_user_archive_recommendations,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_breaches as read_user_retention_breaches,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_guidance as read_user_retention_guidance,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_windows as read_user_retention_windows,
)

from zebra_agent_cli.session_memory_counting import (
    _session_workspace_root,
    _sum_overdue_archive_recommendation_counts,
    _sum_overdue_retention_breach_counts,
    _sum_overdue_retention_guidance_counts,
    _sum_overdue_retention_window_counts,
    _sum_overdue_scope_count,
)
from zebra_agent_cli.session_memory_ranking import (
    _parse_as_of,
)
from zebra_agent_cli.session_memory_resolution_priority_read import (
    _highest_priority_overdue_archive_recommendation_scope,
)
from zebra_agent_cli.session_memory_retention_priority_read import (
    _highest_priority_overdue_retention_breach_scope,
    _highest_priority_overdue_retention_guidance_scope,
    _highest_priority_overdue_retention_window_scope,
)


def read_session_memory_overdue_archive_recommendations(
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
            **read_repo_overdue_archive_recommendations(
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
                **read_user_archive_recommendations(
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
                **read_tenant_archive_recommendations(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_recommendation = _highest_priority_overdue_archive_recommendation_scope(scopes)
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
        "overdue_archive_recommendation_counts": _sum_overdue_archive_recommendation_counts(scopes),
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
            None if highest_recommendation is None else highest_recommendation["target_memory_id"]
        ),
        "highest_priority_overdue_archive_reasons": (
            []
            if highest_recommendation is None
            else highest_recommendation["overdue_archive_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_guidance(
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
            **read_repo_overdue_retention_guidance(
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
                **read_user_retention_guidance(
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
                **read_tenant_retention_guidance(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_guidance = _highest_priority_overdue_retention_guidance_scope(scopes)
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
        "overdue_retention_guidance_counts": _sum_overdue_retention_guidance_counts(scopes),
        "highest_priority_overdue_retention_guidance": (
            None if highest_guidance is None else highest_guidance["overdue_retention_guidance"]
        ),
        "highest_priority_overdue_retention_priority": (
            None if highest_guidance is None else highest_guidance["overdue_retention_priority"]
        ),
        "highest_priority_overdue_retention_scope_kind": (
            None if highest_guidance is None else highest_guidance["scope_kind"]
        ),
        "highest_priority_overdue_retention_scope_id": (
            None if highest_guidance is None else highest_guidance["scope_id"]
        ),
        "highest_priority_overdue_retention_bucket": (
            None if highest_guidance is None else highest_guidance["overdue_retention_bucket"]
        ),
        "highest_priority_overdue_retention_target_memory_id": (
            None if highest_guidance is None else highest_guidance["target_memory_id"]
        ),
        "highest_priority_overdue_retention_reasons": (
            [] if highest_guidance is None else highest_guidance["overdue_retention_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_windows(
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
            **read_repo_overdue_retention_windows(
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
                **read_user_retention_windows(
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
                **read_tenant_retention_windows(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_window = _highest_priority_overdue_retention_window_scope(scopes)
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
        "overdue_retention_window_counts": _sum_overdue_retention_window_counts(scopes),
        "highest_priority_overdue_retention_window": (
            None if highest_window is None else highest_window["overdue_retention_window"]
        ),
        "highest_priority_overdue_retention_window_priority": (
            None if highest_window is None else highest_window["overdue_retention_window_priority"]
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
            [] if highest_window is None else highest_window["overdue_retention_window_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_breaches(
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
            **read_repo_overdue_retention_breaches(
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
                **read_user_retention_breaches(
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
                **read_tenant_retention_breaches(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_breach = _highest_priority_overdue_retention_breach_scope(scopes)
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
        "overdue_retention_breach_counts": _sum_overdue_retention_breach_counts(scopes),
        "highest_priority_overdue_retention_breach": (
            None if highest_breach is None else highest_breach["overdue_retention_breach"]
        ),
        "highest_priority_overdue_retention_breach_priority": (
            None if highest_breach is None else highest_breach["overdue_retention_breach_priority"]
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
            [] if highest_breach is None else highest_breach["overdue_retention_breach_reasons"]
        ),
        "scopes": scopes,
    }
