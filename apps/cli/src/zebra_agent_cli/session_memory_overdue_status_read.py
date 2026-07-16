from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_follow_up_overdue_flags as read_repo_overdue_flags,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_age_buckets as read_repo_overdue_age_buckets,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_type_rollups as read_repo_overdue_types,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_follow_up_overdue_flags as read_tenant_overdue_flags,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_age_buckets as read_tenant_overdue_age_buckets,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_type_rollups as read_tenant_overdue_types,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_follow_up_overdue_flags as read_user_overdue_flags,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_age_buckets as read_user_overdue_age_buckets,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_type_rollups as read_user_overdue_types,
)

from zebra_agent_cli.session_memory_counting import (
    _session_workspace_root,
    _sum_overdue_age_bucket_counts,
    _sum_overdue_memory_type_counts,
    _sum_overdue_scope_count,
)
from zebra_agent_cli.session_memory_priority_read import (
    _highest_priority_overdue_age_scope,
    _highest_priority_overdue_scope,
    _highest_priority_overdue_type_scope,
)
from zebra_agent_cli.session_memory_ranking import (
    _parse_as_of,
)


def read_session_memory_overdue_flags(
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
            **read_repo_overdue_flags(
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
                **read_user_overdue_flags(
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
                **read_tenant_overdue_flags(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_overdue = _highest_priority_overdue_scope(scopes)
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
        "highest_priority_overdue_scope_kind": (
            None if highest_overdue is None else highest_overdue["scope_kind"]
        ),
        "highest_priority_overdue_scope_id": (
            None if highest_overdue is None else highest_overdue["scope_id"]
        ),
        "highest_priority_overdue_priority": (
            None if highest_overdue is None else highest_overdue["follow_up_overdue_priority"]
        ),
        "highest_priority_overdue_since": (
            None if highest_overdue is None else highest_overdue["follow_up_overdue_since"]
        ),
        "highest_priority_overdue_target_memory_id": (
            None if highest_overdue is None else highest_overdue["target_memory_id"]
        ),
        "highest_priority_overdue_reasons": (
            [] if highest_overdue is None else highest_overdue["follow_up_overdue_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_age_buckets(
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
            **read_repo_overdue_age_buckets(
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
                **read_user_overdue_age_buckets(
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
                **read_tenant_overdue_age_buckets(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_overdue_age = _highest_priority_overdue_age_scope(scopes)
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "reference_at": effective_as_of.isoformat(),
        "scope_count": len(scopes),
        "overdue_age_bucket_counts": _sum_overdue_age_bucket_counts(scopes),
        "highest_priority_overdue_age_bucket": (
            None if highest_overdue_age is None else highest_overdue_age["overdue_age_bucket"]
        ),
        "highest_priority_overdue_age_scope_kind": (
            None if highest_overdue_age is None else highest_overdue_age["scope_kind"]
        ),
        "highest_priority_overdue_age_scope_id": (
            None if highest_overdue_age is None else highest_overdue_age["scope_id"]
        ),
        "highest_priority_overdue_age_seconds": (
            None if highest_overdue_age is None else highest_overdue_age["overdue_age_seconds"]
        ),
        "highest_priority_overdue_age_days": (
            None if highest_overdue_age is None else highest_overdue_age["overdue_age_days"]
        ),
        "highest_priority_overdue_age_target_memory_id": (
            None if highest_overdue_age is None else highest_overdue_age["target_memory_id"]
        ),
        "highest_priority_overdue_age_reasons": (
            [] if highest_overdue_age is None else highest_overdue_age["overdue_age_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_type_rollups(
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
            **read_repo_overdue_types(
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
                **read_user_overdue_types(
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
                **read_tenant_overdue_types(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_overdue_type = _highest_priority_overdue_type_scope(scopes)
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
        "overdue_memory_type_counts": _sum_overdue_memory_type_counts(scopes),
        "highest_priority_overdue_memory_type": (
            None
            if highest_overdue_type is None
            else highest_overdue_type["highest_overdue_memory_type"]
        ),
        "highest_priority_overdue_memory_type_count": (
            None
            if highest_overdue_type is None
            else highest_overdue_type["highest_overdue_memory_type_count"]
        ),
        "highest_priority_overdue_type_scope_kind": (
            None if highest_overdue_type is None else highest_overdue_type["scope_kind"]
        ),
        "highest_priority_overdue_type_scope_id": (
            None if highest_overdue_type is None else highest_overdue_type["scope_id"]
        ),
        "highest_priority_overdue_type_target_memory_id": (
            None if highest_overdue_type is None else highest_overdue_type["target_memory_id"]
        ),
        "highest_priority_overdue_target_memory_type": (
            None
            if highest_overdue_type is None
            else highest_overdue_type["overdue_target_memory_type"]
        ),
        "highest_priority_overdue_type_reasons": (
            []
            if highest_overdue_type is None
            else highest_overdue_type["overdue_type_rollup_reasons"]
        ),
        "scopes": scopes,
    }
