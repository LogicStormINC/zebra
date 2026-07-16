from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_backlog_pressure_signals as read_repo_pressure_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_governance_signals as read_repo_memory_governance_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_queue_summary as read_repo_memory_queue_summary_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_review_velocity_signals as read_repo_velocity_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_backlog_pressure_signals as read_tenant_pressure_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_governance_signals as read_tenant_memory_governance_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_queue_summary as read_tenant_memory_queue_summary_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_review_velocity_signals as read_tenant_velocity_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_backlog_pressure_signals as read_user_pressure_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_governance_signals as read_user_memory_governance_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_queue_summary as read_user_memory_queue_summary_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_review_velocity_signals as read_user_velocity_signals,
)

from zebra_agent_cli.session_memory_counting import (
    _highest_pressure_scope,
    _latest_review_scope,
    _session_workspace_root,
    _sum_age_bucket_counts,
    _sum_pending_counts,
    _sum_pressure_level_counts,
    _sum_recent_review_counts,
    _sum_reviewed_counts,
    _sum_status_counts,
)
from zebra_agent_cli.session_memory_ranking import (
    _parse_as_of,
)


def read_session_memory_governance_signals(
    *,
    database_path: Path,
    session_id: str,
    user_id: str | None,
    tenant_id: str | None,
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
    scopes: list[dict[str, object]] = [
        {
            "scope_kind": "repo",
            "scope_id": str(workspace_root),
            **read_repo_memory_governance_signals_inventory(
                database_path=database_path,
                repo_id=str(workspace_root),
            ),
        }
    ]
    if user_id is not None:
        scopes.append(
            {
                "scope_kind": "user",
                "scope_id": user_id,
                **read_user_memory_governance_signals_inventory(
                    database_path=database_path,
                    user_id=user_id,
                ),
            }
        )
    if tenant_id is not None:
        scopes.append(
            {
                "scope_kind": "tenant",
                "scope_id": tenant_id,
                **read_tenant_memory_governance_signals_inventory(
                    database_path=database_path,
                    tenant_id=tenant_id,
                ),
            }
        )
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "scope_count": len(scopes),
        "total_pending_count": _sum_pending_counts(scopes),
        "total_reviewed_count": _sum_reviewed_counts(scopes),
        "review_status_totals": _sum_status_counts(scopes),
        "scopes": scopes,
    }


def read_session_memory_review_velocity_signals(
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
            **read_repo_velocity_signals(
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
                **read_user_velocity_signals(
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
                **read_tenant_velocity_signals(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    latest_review = _latest_review_scope(scopes)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "reference_at": effective_as_of.isoformat(),
        "scope_count": len(scopes),
        "total_reviewed_count": _sum_reviewed_counts(scopes),
        "total_reviewed_last_24h_count": _sum_recent_review_counts(
            scopes,
            "reviewed_last_24h_count",
        ),
        "total_reviewed_last_7d_count": _sum_recent_review_counts(
            scopes,
            "reviewed_last_7d_count",
        ),
        "total_reviewed_last_30d_count": _sum_recent_review_counts(
            scopes,
            "reviewed_last_30d_count",
        ),
        "latest_review_scope_kind": (
            None if latest_review is None else latest_review["scope_kind"]
        ),
        "latest_review_scope_id": (None if latest_review is None else latest_review["scope_id"]),
        "latest_reviewed_at": (None if latest_review is None else latest_review["recorded_at"]),
        "latest_review_status": (None if latest_review is None else latest_review["status"]),
        "latest_review_operator": (None if latest_review is None else latest_review["operator"]),
        "latest_review_window": (None if latest_review is None else latest_review["window"]),
        "scopes": scopes,
    }


def read_session_memory_backlog_pressure_signals(
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
            **read_repo_pressure_signals(
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
                **read_user_pressure_signals(
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
                **read_tenant_pressure_signals(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_pressure = _highest_pressure_scope(scopes)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
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
    }


def read_session_memory_operations_overview(
    *,
    database_path: Path,
    session_id: str,
    user_id: str | None,
    tenant_id: str | None,
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
    scopes: list[dict[str, object]] = [
        {
            "scope_kind": "repo",
            "scope_id": str(workspace_root),
            **read_repo_memory_queue_summary_inventory(
                database_path=database_path,
                repo_id=str(workspace_root),
            ),
        }
    ]
    if user_id is not None:
        scopes.append(
            {
                "scope_kind": "user",
                "scope_id": user_id,
                **read_user_memory_queue_summary_inventory(
                    database_path=database_path,
                    user_id=user_id,
                ),
            }
        )
    if tenant_id is not None:
        scopes.append(
            {
                "scope_kind": "tenant",
                "scope_id": tenant_id,
                **read_tenant_memory_queue_summary_inventory(
                    database_path=database_path,
                    tenant_id=tenant_id,
                ),
            }
        )
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "scope_count": len(scopes),
        "total_pending_count": _sum_pending_counts(scopes),
        "scopes": scopes,
    }
