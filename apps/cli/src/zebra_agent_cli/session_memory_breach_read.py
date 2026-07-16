from __future__ import annotations

from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breach_actions as read_repo_retention_breach_actions,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breach_aging as read_repo_retention_breach_aging,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breach_lanes as read_repo_retention_breach_lanes,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_breach_owner_targets as read_repo_owner_targets,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_breach_actions as read_tenant_retention_breach_actions,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_breach_aging as read_tenant_retention_breach_aging,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_breach_lanes as read_tenant_retention_breach_lanes,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_breach_owner_targets as read_tenant_owner_targets,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_breach_actions as read_user_retention_breach_actions,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_breach_aging as read_user_retention_breach_aging,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_breach_lanes as read_user_retention_breach_lanes,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_breach_owner_targets as read_user_owner_targets,
)

from zebra_agent_cli.session_memory_counting import (
    _session_workspace_root,
    _sum_overdue_retention_breach_action_counts,
    _sum_overdue_retention_breach_age_bucket_counts,
    _sum_overdue_retention_breach_lane_counts,
    _sum_overdue_retention_breach_owner_target_counts,
    _sum_overdue_scope_count,
)
from zebra_agent_cli.session_memory_ranking import (
    _parse_as_of,
)
from zebra_agent_cli.session_memory_retention_priority_read import (
    _highest_priority_overdue_retention_breach_action_scope,
    _highest_priority_overdue_retention_breach_aging_scope,
    _highest_priority_overdue_retention_breach_lane_scope,
    _highest_priority_overdue_retention_breach_owner_target_scope,
)


def read_session_memory_overdue_retention_breach_aging(
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
            **read_repo_retention_breach_aging(
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
                **read_user_retention_breach_aging(
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
                **read_tenant_retention_breach_aging(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_aging = _highest_priority_overdue_retention_breach_aging_scope(scopes)
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
        "overdue_retention_breach_age_bucket_counts": (
            _sum_overdue_retention_breach_age_bucket_counts(scopes)
        ),
        "highest_priority_overdue_retention_breach_age_bucket": (
            None if highest_aging is None else highest_aging["overdue_retention_breach_age_bucket"]
        ),
        "highest_priority_overdue_retention_breach_age_scope_kind": (
            None if highest_aging is None else highest_aging["scope_kind"]
        ),
        "highest_priority_overdue_retention_breach_age_scope_id": (
            None if highest_aging is None else highest_aging["scope_id"]
        ),
        "highest_priority_overdue_retention_breach_age_seconds": (
            None if highest_aging is None else highest_aging["overdue_retention_breach_age_seconds"]
        ),
        "highest_priority_overdue_retention_breach_age_days": (
            None if highest_aging is None else highest_aging["overdue_retention_breach_age_days"]
        ),
        "highest_priority_overdue_retention_breach_age_reasons": (
            [] if highest_aging is None else highest_aging["overdue_retention_breach_age_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_breach_actions(
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
            **read_repo_retention_breach_actions(
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
                **read_user_retention_breach_actions(
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
                **read_tenant_retention_breach_actions(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_action = _highest_priority_overdue_retention_breach_action_scope(scopes)
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
        "overdue_retention_breach_action_counts": (
            _sum_overdue_retention_breach_action_counts(scopes)
        ),
        "highest_priority_overdue_retention_breach_action": (
            None if highest_action is None else highest_action["overdue_retention_breach_action"]
        ),
        "highest_priority_overdue_retention_breach_action_priority": (
            None
            if highest_action is None
            else highest_action["overdue_retention_breach_action_priority"]
        ),
        "highest_priority_overdue_retention_breach_action_scope_kind": (
            None if highest_action is None else highest_action["scope_kind"]
        ),
        "highest_priority_overdue_retention_breach_action_scope_id": (
            None if highest_action is None else highest_action["scope_id"]
        ),
        "highest_priority_overdue_retention_breach_action_target_memory_id": (
            None if highest_action is None else highest_action["target_memory_id"]
        ),
        "highest_priority_overdue_retention_breach_action_reasons": (
            []
            if highest_action is None
            else highest_action["overdue_retention_breach_action_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_breach_lanes(
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
            **read_repo_retention_breach_lanes(
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
                **read_user_retention_breach_lanes(
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
                **read_tenant_retention_breach_lanes(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_lane = _highest_priority_overdue_retention_breach_lane_scope(scopes)
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
        "overdue_retention_breach_lane_counts": (_sum_overdue_retention_breach_lane_counts(scopes)),
        "highest_priority_overdue_retention_breach_lane": (
            None if highest_lane is None else highest_lane["overdue_retention_breach_lane"]
        ),
        "highest_priority_overdue_retention_breach_lane_priority": (
            None if highest_lane is None else highest_lane["overdue_retention_breach_lane_priority"]
        ),
        "highest_priority_overdue_retention_breach_lane_scope_kind": (
            None if highest_lane is None else highest_lane["scope_kind"]
        ),
        "highest_priority_overdue_retention_breach_lane_scope_id": (
            None if highest_lane is None else highest_lane["scope_id"]
        ),
        "highest_priority_overdue_retention_breach_lane_target_memory_id": (
            None if highest_lane is None else highest_lane["target_memory_id"]
        ),
        "highest_priority_overdue_retention_breach_lane_reasons": (
            [] if highest_lane is None else highest_lane["overdue_retention_breach_lane_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_breach_owner_targets(
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
            **read_repo_owner_targets(
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
                **read_user_owner_targets(
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
                **read_tenant_owner_targets(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_owner_target = _highest_priority_overdue_retention_breach_owner_target_scope(scopes)
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
        "overdue_retention_breach_owner_target_counts": (
            _sum_overdue_retention_breach_owner_target_counts(scopes)
        ),
        "highest_priority_overdue_retention_breach_owner_target": (
            None
            if highest_owner_target is None
            else highest_owner_target["overdue_retention_breach_owner_target"]
        ),
        "highest_priority_overdue_retention_breach_owner_target_priority": (
            None
            if highest_owner_target is None
            else highest_owner_target["overdue_retention_breach_owner_target_priority"]
        ),
        "highest_priority_overdue_retention_breach_owner_target_scope_kind": (
            None if highest_owner_target is None else highest_owner_target["scope_kind"]
        ),
        "highest_priority_overdue_retention_breach_owner_target_scope_id": (
            None if highest_owner_target is None else highest_owner_target["scope_id"]
        ),
        "highest_priority_overdue_retention_breach_owner_target_memory_id": (
            None if highest_owner_target is None else highest_owner_target["target_memory_id"]
        ),
        "highest_priority_overdue_retention_breach_owner_target_reasons": (
            []
            if highest_owner_target is None
            else highest_owner_target["overdue_retention_breach_owner_target_reasons"]
        ),
        "scopes": scopes,
    }
