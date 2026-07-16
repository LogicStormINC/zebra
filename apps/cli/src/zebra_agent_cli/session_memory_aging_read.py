from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_backlog_aging_signals as read_repo_memory_backlog_aging_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_backlog_aging_signals as read_tenant_memory_backlog_aging_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_backlog_aging_signals as read_user_memory_backlog_aging_signals_inventory,
)

from zebra_agent_cli.session_memory_counting import (
    _session_workspace_root,
    _sum_age_bucket_counts,
    _sum_pending_counts,
)
from zebra_agent_cli.session_memory_ranking import (
    _oldest_pending_scope,
    _parse_as_of,
)


def read_session_memory_backlog_aging_signals(
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
            **read_repo_memory_backlog_aging_signals_inventory(
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
                **read_user_memory_backlog_aging_signals_inventory(
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
                **read_tenant_memory_backlog_aging_signals_inventory(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    oldest_pending = _oldest_pending_scope(scopes)
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
        "oldest_pending_scope_kind": (
            None if oldest_pending is None else oldest_pending["scope_kind"]
        ),
        "oldest_pending_scope_id": (None if oldest_pending is None else oldest_pending["scope_id"]),
        "oldest_pending_memory_id": (
            None if oldest_pending is None else oldest_pending["memory_id"]
        ),
        "oldest_pending_captured_at": (
            None if oldest_pending is None else oldest_pending["captured_at"]
        ),
        "oldest_pending_age_seconds": (
            None if oldest_pending is None else oldest_pending["age_seconds"]
        ),
        "oldest_pending_age_days": (None if oldest_pending is None else oldest_pending["age_days"]),
        "scopes": scopes,
    }
