from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_backlog_aging_signals as read_repo_memory_backlog_aging_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_backlog_pressure_signals as read_repo_pressure_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_escalation_follow_up_windows as read_repo_follow_up_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_follow_up_overdue_flags as read_repo_overdue_flags,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_governance_signals as read_repo_memory_governance_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_inventory,
    read_repo_memory_overdue_retention_breach_follow_through_completion_states,
    read_repo_memory_overdue_retention_breach_follow_through_modes,
    read_repo_memory_overdue_retention_breach_follow_through_outcomes,
    read_repo_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_repo_memory_overdue_retention_breach_follow_through_verification_states,
    read_tenant_memory_inventory,
    read_tenant_memory_overdue_retention_breach_follow_through_completion_states,
    read_tenant_memory_overdue_retention_breach_follow_through_modes,
    read_tenant_memory_overdue_retention_breach_follow_through_outcomes,
    read_tenant_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_tenant_memory_overdue_retention_breach_follow_through_verification_states,
    read_user_memory_inventory,
    read_user_memory_overdue_retention_breach_follow_through_completion_states,
    read_user_memory_overdue_retention_breach_follow_through_modes,
    read_user_memory_overdue_retention_breach_follow_through_outcomes,
    read_user_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_user_memory_overdue_retention_breach_follow_through_verification_states,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_age_buckets as read_repo_overdue_age_buckets,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_archive_recommendations as read_repo_overdue_archive_recommendations,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_closure_decisions as read_repo_overdue_closure_decisions,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_escalation_lanes as read_repo_overdue_escalation_lanes,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_intervention_hints as read_repo_overdue_interventions,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_recovery_paths as read_repo_overdue_recovery_paths,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_resolution_checkpoints as read_repo_overdue_resolution_checkpoints,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_resolution_outcomes as read_repo_overdue_resolution_outcomes,
)
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
    read_repo_memory_overdue_retention_breaches as read_repo_overdue_retention_breaches,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_guidance as read_repo_overdue_retention_guidance,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_retention_windows as read_repo_overdue_retention_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_trend_signals as read_repo_overdue_trends,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_type_rollups as read_repo_overdue_types,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_overdue_visibility_rollups as read_repo_overdue_visibility,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_pressure_action_hints as read_repo_action_hints,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_pressure_escalation_recommendations as read_repo_escalations,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_queue as read_repo_memory_queue_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_queue_summary as read_repo_memory_queue_summary_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_repo_memory_review_velocity_signals as read_repo_velocity_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_backlog_aging_signals as read_tenant_memory_backlog_aging_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_backlog_pressure_signals as read_tenant_pressure_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_escalation_follow_up_windows as read_tenant_follow_up_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_follow_up_overdue_flags as read_tenant_overdue_flags,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_governance_signals as read_tenant_memory_governance_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_age_buckets as read_tenant_overdue_age_buckets,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_archive_recommendations as read_tenant_archive_recommendations,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_closure_decisions as read_tenant_overdue_closure_decisions,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_escalation_lanes as read_tenant_overdue_escalation_lanes,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_intervention_hints as read_tenant_overdue_interventions,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_recovery_paths as read_tenant_overdue_recovery_paths,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_resolution_checkpoints as read_tenant_overdue_resolution_checkpoints,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_resolution_outcomes as read_tenant_overdue_resolution_outcomes,
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
    read_tenant_memory_overdue_retention_breaches as read_tenant_retention_breaches,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_guidance as read_tenant_retention_guidance,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_retention_windows as read_tenant_retention_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_trend_signals as read_tenant_overdue_trends,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_type_rollups as read_tenant_overdue_types,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_overdue_visibility_rollups as read_tenant_overdue_visibility,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_pressure_action_hints as read_tenant_action_hints,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_pressure_escalation_recommendations as read_tenant_escalations,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_queue as read_tenant_memory_queue_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_queue_summary as read_tenant_memory_queue_summary_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_review_velocity_signals as read_tenant_velocity_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_backlog_aging_signals as read_user_memory_backlog_aging_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_backlog_pressure_signals as read_user_pressure_signals,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_escalation_follow_up_windows as read_user_follow_up_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_follow_up_overdue_flags as read_user_overdue_flags,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_governance_signals as read_user_memory_governance_signals_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_age_buckets as read_user_overdue_age_buckets,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_archive_recommendations as read_user_archive_recommendations,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_closure_decisions as read_user_overdue_closure_decisions,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_escalation_lanes as read_user_overdue_escalation_lanes,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_intervention_hints as read_user_overdue_interventions,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_recovery_paths as read_user_overdue_recovery_paths,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_resolution_checkpoints as read_user_overdue_resolution_checkpoints,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_resolution_outcomes as read_user_overdue_resolution_outcomes,
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
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_breaches as read_user_retention_breaches,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_guidance as read_user_retention_guidance,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_retention_windows as read_user_retention_windows,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_trend_signals as read_user_overdue_trends,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_type_rollups as read_user_overdue_types,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_overdue_visibility_rollups as read_user_overdue_visibility,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_pressure_action_hints as read_user_action_hints,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_pressure_escalation_recommendations as read_user_escalations,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_queue as read_user_memory_queue_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_queue_summary as read_user_memory_queue_summary_inventory,
)
from zebra_agent_api.memory_inventory_read import (
    read_user_memory_review_velocity_signals as read_user_velocity_signals,
)
from zebra_agent_api.session_context import session_workspace_root

read_repo_follow_through_modes = (
    read_repo_memory_overdue_retention_breach_follow_through_modes
)
read_repo_follow_through_outcomes = (
    read_repo_memory_overdue_retention_breach_follow_through_outcomes
)
read_repo_follow_through_completion_states = (
    read_repo_memory_overdue_retention_breach_follow_through_completion_states
)
read_repo_follow_through_verification_states = (
    read_repo_memory_overdue_retention_breach_follow_through_verification_states
)
read_repo_follow_through_verification_outcomes = (
    read_repo_memory_overdue_retention_breach_follow_through_verification_outcomes
)
read_tenant_follow_through_modes = (
    read_tenant_memory_overdue_retention_breach_follow_through_modes
)
read_tenant_follow_through_outcomes = (
    read_tenant_memory_overdue_retention_breach_follow_through_outcomes
)
read_tenant_follow_through_completion_states = (
    read_tenant_memory_overdue_retention_breach_follow_through_completion_states
)
read_tenant_follow_through_verification_states = (
    read_tenant_memory_overdue_retention_breach_follow_through_verification_states
)
read_tenant_follow_through_verification_outcomes = (
    read_tenant_memory_overdue_retention_breach_follow_through_verification_outcomes
)
read_user_follow_through_modes = (
    read_user_memory_overdue_retention_breach_follow_through_modes
)
read_user_follow_through_outcomes = (
    read_user_memory_overdue_retention_breach_follow_through_outcomes
)
read_user_follow_through_completion_states = (
    read_user_memory_overdue_retention_breach_follow_through_completion_states
)
read_user_follow_through_verification_states = (
    read_user_memory_overdue_retention_breach_follow_through_verification_states
)
read_user_follow_through_verification_outcomes = (
    read_user_memory_overdue_retention_breach_follow_through_verification_outcomes
)


def read_session_memory(
    *,
    database_path: Path,
    session_id: str,
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
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "memories": read_repo_memory_inventory(
            database_path=database_path,
            repo_id=str(workspace_root),
        ),
    }


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
        "oldest_pending_scope_id": (
            None if oldest_pending is None else oldest_pending["scope_id"]
        ),
        "oldest_pending_memory_id": (
            None if oldest_pending is None else oldest_pending["memory_id"]
        ),
        "oldest_pending_captured_at": (
            None if oldest_pending is None else oldest_pending["captured_at"]
        ),
        "oldest_pending_age_seconds": (
            None if oldest_pending is None else oldest_pending["age_seconds"]
        ),
        "oldest_pending_age_days": (
            None if oldest_pending is None else oldest_pending["age_days"]
        ),
        "scopes": scopes,
    }


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
            None
            if highest_escalation is None
            else highest_escalation["escalation_recommendation"]
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
            None
            if highest_overdue is None
            else highest_overdue["follow_up_overdue_priority"]
        ),
        "highest_priority_overdue_since": (
            None if highest_overdue is None else highest_overdue["follow_up_overdue_since"]
        ),
        "highest_priority_overdue_target_memory_id": (
            None if highest_overdue is None else highest_overdue["target_memory_id"]
        ),
        "highest_priority_overdue_reasons": (
            []
            if highest_overdue is None
            else highest_overdue["follow_up_overdue_reasons"]
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
            None
            if highest_overdue_age is None
            else highest_overdue_age["overdue_age_bucket"]
        ),
        "highest_priority_overdue_age_scope_kind": (
            None if highest_overdue_age is None else highest_overdue_age["scope_kind"]
        ),
        "highest_priority_overdue_age_scope_id": (
            None if highest_overdue_age is None else highest_overdue_age["scope_id"]
        ),
        "highest_priority_overdue_age_seconds": (
            None
            if highest_overdue_age is None
            else highest_overdue_age["overdue_age_seconds"]
        ),
        "highest_priority_overdue_age_days": (
            None
            if highest_overdue_age is None
            else highest_overdue_age["overdue_age_days"]
        ),
        "highest_priority_overdue_age_target_memory_id": (
            None
            if highest_overdue_age is None
            else highest_overdue_age["target_memory_id"]
        ),
        "highest_priority_overdue_age_reasons": (
            []
            if highest_overdue_age is None
            else highest_overdue_age["overdue_age_reasons"]
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
            None
            if highest_overdue_visibility is None
            else highest_overdue_visibility["scope_kind"]
        ),
        "highest_priority_overdue_visibility_scope_id": (
            None
            if highest_overdue_visibility is None
            else highest_overdue_visibility["scope_id"]
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
            None
            if highest_overdue_trend is None
            else highest_overdue_trend["overdue_trend_signal"]
        ),
        "highest_priority_overdue_trend_rank": (
            None
            if highest_overdue_trend is None
            else highest_overdue_trend["overdue_trend_rank"]
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
            []
            if highest_overdue_trend is None
            else highest_overdue_trend["overdue_trend_reasons"]
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


def read_session_memory_overdue_escalation_lanes(
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
            **read_repo_overdue_escalation_lanes(
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
                **read_user_overdue_escalation_lanes(
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
                **read_tenant_overdue_escalation_lanes(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_lane = _highest_priority_overdue_escalation_lane_scope(scopes)
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
        "overdue_escalation_lane_counts": _sum_overdue_escalation_lane_counts(scopes),
        "highest_priority_overdue_escalation_lane": (
            None if highest_lane is None else highest_lane["overdue_escalation_lane"]
        ),
        "highest_priority_overdue_escalation_priority": (
            None if highest_lane is None else highest_lane["overdue_escalation_priority"]
        ),
        "highest_priority_overdue_escalation_scope_kind": (
            None if highest_lane is None else highest_lane["scope_kind"]
        ),
        "highest_priority_overdue_escalation_scope_id": (
            None if highest_lane is None else highest_lane["scope_id"]
        ),
        "highest_priority_overdue_escalation_target_memory_id": (
            None if highest_lane is None else highest_lane["target_memory_id"]
        ),
        "highest_priority_overdue_escalation_reasons": (
            [] if highest_lane is None else highest_lane["overdue_escalation_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_recovery_paths(
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
            **read_repo_overdue_recovery_paths(
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
                **read_user_overdue_recovery_paths(
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
                **read_tenant_overdue_recovery_paths(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_recovery = _highest_priority_overdue_recovery_path_scope(scopes)
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
        "overdue_recovery_path_counts": _sum_overdue_recovery_path_counts(scopes),
        "highest_priority_overdue_recovery_path": (
            None if highest_recovery is None else highest_recovery["overdue_recovery_path"]
        ),
        "highest_priority_overdue_recovery_priority": (
            None
            if highest_recovery is None
            else highest_recovery["overdue_recovery_priority"]
        ),
        "highest_priority_overdue_recovery_scope_kind": (
            None if highest_recovery is None else highest_recovery["scope_kind"]
        ),
        "highest_priority_overdue_recovery_scope_id": (
            None if highest_recovery is None else highest_recovery["scope_id"]
        ),
        "highest_priority_overdue_recovery_target_memory_id": (
            None if highest_recovery is None else highest_recovery["target_memory_id"]
        ),
        "highest_priority_overdue_recovery_reasons": (
            []
            if highest_recovery is None
            else highest_recovery["overdue_recovery_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_resolution_checkpoints(
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
            **read_repo_overdue_resolution_checkpoints(
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
                **read_user_overdue_resolution_checkpoints(
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
                **read_tenant_overdue_resolution_checkpoints(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_checkpoint = _highest_priority_overdue_resolution_checkpoint_scope(scopes)
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
    }


def read_session_memory_overdue_resolution_outcomes(
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
            **read_repo_overdue_resolution_outcomes(
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
                **read_user_overdue_resolution_outcomes(
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
                **read_tenant_overdue_resolution_outcomes(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_outcome = _highest_priority_overdue_resolution_outcome_scope(scopes)
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
        "overdue_resolution_outcome_counts": _sum_overdue_resolution_outcome_counts(scopes),
        "highest_priority_overdue_resolution_outcome": (
            None if highest_outcome is None else highest_outcome["overdue_resolution_outcome"]
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
    }


def read_session_memory_overdue_closure_decisions(
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
            **read_repo_overdue_closure_decisions(
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
                **read_user_overdue_closure_decisions(
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
                **read_tenant_overdue_closure_decisions(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_decision = _highest_priority_overdue_closure_decision_scope(scopes)
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
        "overdue_closure_decision_counts": _sum_overdue_closure_decision_counts(scopes),
        "highest_priority_overdue_closure_decision": (
            None if highest_decision is None else highest_decision["overdue_closure_decision"]
        ),
        "highest_priority_overdue_closure_priority": (
            None if highest_decision is None else highest_decision["overdue_closure_priority"]
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
            []
            if highest_decision is None
            else highest_decision["overdue_closure_reasons"]
        ),
        "scopes": scopes,
    }


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
    highest_recommendation = _highest_priority_overdue_archive_recommendation_scope(
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
        "overdue_retention_guidance_counts": _sum_overdue_retention_guidance_counts(
            scopes
        ),
        "highest_priority_overdue_retention_guidance": (
            None
            if highest_guidance is None
            else highest_guidance["overdue_retention_guidance"]
        ),
        "highest_priority_overdue_retention_priority": (
            None
            if highest_guidance is None
            else highest_guidance["overdue_retention_priority"]
        ),
        "highest_priority_overdue_retention_scope_kind": (
            None if highest_guidance is None else highest_guidance["scope_kind"]
        ),
        "highest_priority_overdue_retention_scope_id": (
            None if highest_guidance is None else highest_guidance["scope_id"]
        ),
        "highest_priority_overdue_retention_bucket": (
            None
            if highest_guidance is None
            else highest_guidance["overdue_retention_bucket"]
        ),
        "highest_priority_overdue_retention_target_memory_id": (
            None
            if highest_guidance is None
            else highest_guidance["target_memory_id"]
        ),
        "highest_priority_overdue_retention_reasons": (
            []
            if highest_guidance is None
            else highest_guidance["overdue_retention_reasons"]
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
        "overdue_retention_window_counts": _sum_overdue_retention_window_counts(
            scopes
        ),
        "highest_priority_overdue_retention_window": (
            None if highest_window is None else highest_window["overdue_retention_window"]
        ),
        "highest_priority_overdue_retention_window_priority": (
            None
            if highest_window is None
            else highest_window["overdue_retention_window_priority"]
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
            []
            if highest_window is None
            else highest_window["overdue_retention_window_reasons"]
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
            None
            if highest_breach is None
            else highest_breach["overdue_retention_breach_priority"]
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
            []
            if highest_breach is None
            else highest_breach["overdue_retention_breach_reasons"]
        ),
        "scopes": scopes,
    }


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
            None
            if highest_aging is None
            else highest_aging["overdue_retention_breach_age_bucket"]
        ),
        "highest_priority_overdue_retention_breach_age_scope_kind": (
            None if highest_aging is None else highest_aging["scope_kind"]
        ),
        "highest_priority_overdue_retention_breach_age_scope_id": (
            None if highest_aging is None else highest_aging["scope_id"]
        ),
        "highest_priority_overdue_retention_breach_age_seconds": (
            None
            if highest_aging is None
            else highest_aging["overdue_retention_breach_age_seconds"]
        ),
        "highest_priority_overdue_retention_breach_age_days": (
            None
            if highest_aging is None
            else highest_aging["overdue_retention_breach_age_days"]
        ),
        "highest_priority_overdue_retention_breach_age_reasons": (
            []
            if highest_aging is None
            else highest_aging["overdue_retention_breach_age_reasons"]
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
            None
            if highest_action is None
            else highest_action["overdue_retention_breach_action"]
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
        "overdue_retention_breach_lane_counts": (
            _sum_overdue_retention_breach_lane_counts(scopes)
        ),
        "highest_priority_overdue_retention_breach_lane": (
            None if highest_lane is None else highest_lane["overdue_retention_breach_lane"]
        ),
        "highest_priority_overdue_retention_breach_lane_priority": (
            None
            if highest_lane is None
            else highest_lane["overdue_retention_breach_lane_priority"]
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
            []
            if highest_lane is None
            else highest_lane["overdue_retention_breach_lane_reasons"]
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
    highest_owner_target = _highest_priority_overdue_retention_breach_owner_target_scope(
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
            None
            if highest_owner_target is None
            else highest_owner_target["target_memory_id"]
        ),
        "highest_priority_overdue_retention_breach_owner_target_reasons": (
            []
            if highest_owner_target is None
            else highest_owner_target["overdue_retention_breach_owner_target_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_breach_follow_through_modes(
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
            **read_repo_follow_through_modes(
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
                **read_user_follow_through_modes(
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
                **read_tenant_follow_through_modes(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_mode = _highest_priority_overdue_retention_breach_follow_through_scope(
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
        "overdue_retention_breach_follow_through_counts": (
            _sum_overdue_retention_breach_follow_through_counts(scopes)
        ),
        "highest_priority_overdue_retention_breach_follow_through_mode": (
            None
            if highest_mode is None
            else highest_mode["overdue_retention_breach_follow_through_mode"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_priority": (
            None
            if highest_mode is None
            else highest_mode["overdue_retention_breach_follow_through_priority"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_scope_kind": (
            None if highest_mode is None else highest_mode["scope_kind"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_scope_id": (
            None if highest_mode is None else highest_mode["scope_id"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_memory_id": (
            None if highest_mode is None else highest_mode["target_memory_id"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_reasons": (
            []
            if highest_mode is None
            else highest_mode["overdue_retention_breach_follow_through_reasons"]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_breach_follow_through_outcomes(
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
            **read_repo_follow_through_outcomes(
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
                **read_user_follow_through_outcomes(
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
                **read_tenant_follow_through_outcomes(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_outcome = _highest_priority_overdue_retention_breach_follow_through_outcome_scope(
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
        "overdue_retention_breach_follow_through_outcome_counts": (
            _sum_overdue_retention_breach_follow_through_outcome_counts(scopes)
        ),
        "highest_priority_overdue_retention_breach_follow_through_outcome": (
            None
            if highest_outcome is None
            else highest_outcome["overdue_retention_breach_follow_through_outcome"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_outcome_priority": (
            None
            if highest_outcome is None
            else highest_outcome[
                "overdue_retention_breach_follow_through_outcome_priority"
            ]
        ),
        "highest_priority_overdue_retention_breach_follow_through_outcome_scope_kind": (
            None if highest_outcome is None else highest_outcome["scope_kind"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_outcome_scope_id": (
            None if highest_outcome is None else highest_outcome["scope_id"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_outcome_memory_id": (
            None if highest_outcome is None else highest_outcome["target_memory_id"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_outcome_reasons": (
            []
            if highest_outcome is None
            else highest_outcome[
                "overdue_retention_breach_follow_through_outcome_reasons"
            ]
        ),
        "scopes": scopes,
    }


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
            else highest_state[
                "overdue_retention_breach_follow_through_completion_state"
            ]
        ),
        "highest_priority_overdue_retention_breach_follow_through_completion_priority": (
            None
            if highest_state is None
            else highest_state[
                "overdue_retention_breach_follow_through_completion_priority"
            ]
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
            else highest_state[
                "overdue_retention_breach_follow_through_completion_reasons"
            ]
        ),
        "scopes": scopes,
    }


def read_session_memory_overdue_retention_breach_follow_through_verification_states(
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
            **read_repo_follow_through_verification_states(
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
                **read_user_follow_through_verification_states(
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
                **read_tenant_follow_through_verification_states(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_state = (
        _highest_priority_overdue_retention_breach_follow_through_verification_scope(
            scopes
        )
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
        "overdue_retention_breach_follow_through_verification_counts": (
            _sum_overdue_retention_breach_follow_through_verification_counts(scopes)
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_state": (
            None
            if highest_state is None
            else highest_state[
                "overdue_retention_breach_follow_through_verification_state"
            ]
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_priority": (
            None
            if highest_state is None
            else highest_state[
                "overdue_retention_breach_follow_through_verification_priority"
            ]
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_scope_kind": (
            None if highest_state is None else highest_state["scope_kind"]
        ),
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
    }


def read_session_memory_overdue_retention_breach_follow_through_verification_outcomes(
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
            **read_repo_follow_through_verification_outcomes(
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
                **read_user_follow_through_verification_outcomes(
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
                **read_tenant_follow_through_verification_outcomes(
                    database_path=database_path,
                    tenant_id=tenant_id,
                    as_of=effective_as_of,
                ),
            }
        )
    highest_outcome = (
        _highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope(
            scopes
        )
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
        "overdue_retention_breach_follow_through_verification_outcome_counts": (
            _sum_overdue_retention_breach_follow_through_verification_outcome_counts(
                scopes
            )
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_outcome": (
            None
            if highest_outcome is None
            else highest_outcome[
                "overdue_retention_breach_follow_through_verification_outcome"
            ]
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_outcome_priority": (
            None
            if highest_outcome is None
            else highest_outcome[
                "overdue_retention_breach_follow_through_verification_outcome_priority"
            ]
        ),
        (
            "highest_priority_overdue_retention_breach_follow_through_"
            "verification_outcome_scope_kind"
        ): (
            None if highest_outcome is None else highest_outcome["scope_kind"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope_id": (
            None if highest_outcome is None else highest_outcome["scope_id"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_outcome_memory_id": (
            None if highest_outcome is None else highest_outcome["target_memory_id"]
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_outcome_reasons": (
            []
            if highest_outcome is None
            else highest_outcome[
                "overdue_retention_breach_follow_through_verification_outcome_reasons"
            ]
        ),
        "scopes": scopes,
    }


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
        "latest_review_scope_id": (
            None if latest_review is None else latest_review["scope_id"]
        ),
        "latest_reviewed_at": (
            None if latest_review is None else latest_review["recorded_at"]
        ),
        "latest_review_status": (
            None if latest_review is None else latest_review["status"]
        ),
        "latest_review_operator": (
            None if latest_review is None else latest_review["operator"]
        ),
        "latest_review_window": (
            None if latest_review is None else latest_review["window"]
        ),
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


def read_session_memory_queue(
    *,
    database_path: Path,
    session_id: str,
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
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        "memories": read_repo_memory_queue_inventory(
            database_path=database_path,
            repo_id=str(workspace_root),
        ),
    }


def read_session_memory_queue_summary(
    *,
    database_path: Path,
    session_id: str,
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
    return {
        "session_id": session_id,
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace_root),
        **read_repo_memory_queue_summary_inventory(
            database_path=database_path,
            repo_id=str(workspace_root),
        ),
    }


def read_user_memory(
    *,
    database_path: Path,
    user_id: str,
) -> dict[str, object]:
    return {
        "database": str(database_path),
        "status": "ok",
        "user_id": user_id,
        "memories": read_user_memory_inventory(
            database_path=database_path,
            user_id=user_id,
        ),
    }


def read_user_memory_queue(
    *,
    database_path: Path,
    user_id: str,
) -> dict[str, object]:
    return {
        "database": str(database_path),
        "status": "ok",
        "user_id": user_id,
        "memories": read_user_memory_queue_inventory(
            database_path=database_path,
            user_id=user_id,
        ),
    }


def read_user_memory_queue_summary(
    *,
    database_path: Path,
    user_id: str,
) -> dict[str, object]:
    return {
        "database": str(database_path),
        "status": "ok",
        "user_id": user_id,
        **read_user_memory_queue_summary_inventory(
            database_path=database_path,
            user_id=user_id,
        ),
    }


def read_tenant_memory(
    *,
    database_path: Path,
    tenant_id: str,
) -> dict[str, object]:
    return {
        "database": str(database_path),
        "status": "ok",
        "tenant_id": tenant_id,
        "memories": read_tenant_memory_inventory(
            database_path=database_path,
            tenant_id=tenant_id,
        ),
    }


def read_tenant_memory_queue(
    *,
    database_path: Path,
    tenant_id: str,
) -> dict[str, object]:
    return {
        "database": str(database_path),
        "status": "ok",
        "tenant_id": tenant_id,
        "memories": read_tenant_memory_queue_inventory(
            database_path=database_path,
            tenant_id=tenant_id,
        ),
    }


def read_tenant_memory_queue_summary(
    *,
    database_path: Path,
    tenant_id: str,
) -> dict[str, object]:
    return {
        "database": str(database_path),
        "status": "ok",
        "tenant_id": tenant_id,
        **read_tenant_memory_queue_summary_inventory(
            database_path=database_path,
            tenant_id=tenant_id,
        ),
    }


def _session_workspace_root(events: Sequence[SessionEvent]) -> Path | None:
    return session_workspace_root(list(events))


def _sum_pending_counts(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        pending_count = scope.get("pending_count")
        if isinstance(pending_count, int) and not isinstance(pending_count, bool):
            total += pending_count
    return total


def _sum_reviewed_counts(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        reviewed_count = scope.get("reviewed_count")
        if isinstance(reviewed_count, int) and not isinstance(reviewed_count, bool):
            total += reviewed_count
    return total


def _sum_status_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("review_status_counts")
        if not isinstance(counts, dict):
            continue
        for status, count in counts.items():
            if not isinstance(status, str):
                continue
            if not isinstance(count, int) or isinstance(count, bool):
                continue
            totals[status] = totals.get(status, 0) + count
    return totals


def _sum_age_bucket_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals = {
        "lt_1d": 0,
        "gte_1d_lt_3d": 0,
        "gte_3d_lt_7d": 0,
        "gte_7d": 0,
    }
    for scope in scopes:
        counts = scope.get("pending_age_buckets")
        if not isinstance(counts, dict):
            continue
        for bucket_name in totals:
            count = counts.get(bucket_name)
            if isinstance(count, int) and not isinstance(count, bool):
                totals[bucket_name] += count
    return totals


def _sum_recent_review_counts(
    scopes: list[dict[str, object]],
    field_name: str,
) -> int:
    total = 0
    for scope in scopes:
        count = scope.get(field_name)
        if isinstance(count, int) and not isinstance(count, bool):
            total += count
    return total


def _latest_review_scope(
    scopes: list[dict[str, object]],
) -> dict[str, str] | None:
    latest: dict[str, str] | None = None
    for scope in scopes:
        recorded_at = scope.get("latest_reviewed_at")
        status = scope.get("latest_review_status")
        operator = scope.get("latest_review_operator")
        window = scope.get("latest_review_window")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        if not (
            isinstance(recorded_at, str)
            and isinstance(status, str)
            and isinstance(operator, str)
            and isinstance(window, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
        ):
            continue
        candidate = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "recorded_at": recorded_at,
            "status": status,
            "operator": operator,
            "window": window,
        }
        if latest is None or recorded_at > latest["recorded_at"]:
            latest = candidate
    return latest


def _sum_pressure_level_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        level = scope.get("pressure_level")
        if not isinstance(level, str):
            continue
        totals[level] = totals.get(level, 0) + 1
    return totals


def _highest_pressure_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        level = scope.get("pressure_level")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        reasons = scope.get("pressure_reasons")
        if not (
            isinstance(level, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "pressure_level": level,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "pressure_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _pressure_rank(level) > _pressure_rank(
            str(highest["pressure_level"])
        ):
            highest = candidate
    return highest


def _sum_action_hint_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        hint = scope.get("action_hint")
        if not isinstance(hint, str):
            continue
        totals[hint] = totals.get(hint, 0) + 1
    return totals


def _sum_escalation_recommendation_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        recommendation = scope.get("escalation_recommendation")
        if not isinstance(recommendation, str):
            continue
        totals[recommendation] = totals.get(recommendation, 0) + 1
    return totals


def _sum_follow_up_window_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        window = scope.get("follow_up_window")
        if not isinstance(window, str):
            continue
        totals[window] = totals.get(window, 0) + 1
    return totals


def _sum_overdue_scope_count(scopes: list[dict[str, object]]) -> int:
    total = 0
    for scope in scopes:
        if scope.get("follow_up_overdue") is True:
            total += 1
    return total


def _sum_overdue_age_bucket_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        bucket = scope.get("overdue_age_bucket")
        if not isinstance(bucket, str):
            continue
        totals[bucket] = totals.get(bucket, 0) + 1
    return totals


def _sum_overdue_memory_type_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("overdue_memory_type_counts")
        if not isinstance(counts, dict):
            continue
        for memory_type, count in counts.items():
            if not isinstance(memory_type, str) or not isinstance(count, int):
                continue
            totals[memory_type] = totals.get(memory_type, 0) + count
    return totals


def _sum_overdue_memory_visibility_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        counts = scope.get("overdue_memory_visibility_counts")
        if not isinstance(counts, dict):
            continue
        for visibility, count in counts.items():
            if not isinstance(visibility, str) or not isinstance(count, int):
                continue
            totals[visibility] = totals.get(visibility, 0) + count
    return totals


def _sum_overdue_trend_signal_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        signal = scope.get("overdue_trend_signal")
        if not isinstance(signal, str):
            continue
        totals[signal] = totals.get(signal, 0) + 1
    return totals


def _sum_overdue_intervention_hint_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        hint = scope.get("overdue_intervention_hint")
        if not isinstance(hint, str):
            continue
        totals[hint] = totals.get(hint, 0) + 1
    return totals


def _sum_overdue_escalation_lane_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        lane = scope.get("overdue_escalation_lane")
        if not isinstance(lane, str):
            continue
        totals[lane] = totals.get(lane, 0) + 1
    return totals


def _sum_overdue_recovery_path_counts(scopes: list[dict[str, object]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        path = scope.get("overdue_recovery_path")
        if not isinstance(path, str):
            continue
        totals[path] = totals.get(path, 0) + 1
    return totals


def _sum_overdue_resolution_checkpoint_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        checkpoint = scope.get("overdue_resolution_checkpoint")
        if not isinstance(checkpoint, str):
            continue
        totals[checkpoint] = totals.get(checkpoint, 0) + 1
    return totals


def _sum_overdue_resolution_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get("overdue_resolution_outcome")
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


def _sum_overdue_closure_decision_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        decision = scope.get("overdue_closure_decision")
        if not isinstance(decision, str):
            continue
        totals[decision] = totals.get(decision, 0) + 1
    return totals


def _sum_overdue_archive_recommendation_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        recommendation = scope.get("overdue_archive_recommendation")
        if not isinstance(recommendation, str):
            continue
        totals[recommendation] = totals.get(recommendation, 0) + 1
    return totals


def _sum_overdue_retention_guidance_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        guidance = scope.get("overdue_retention_guidance")
        if not isinstance(guidance, str):
            continue
        totals[guidance] = totals.get(guidance, 0) + 1
    return totals


def _sum_overdue_retention_window_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        window = scope.get("overdue_retention_window")
        if not isinstance(window, str):
            continue
        totals[window] = totals.get(window, 0) + 1
    return totals


def _sum_overdue_retention_breach_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        breach = scope.get("overdue_retention_breach")
        if not isinstance(breach, str):
            continue
        totals[breach] = totals.get(breach, 0) + 1
    return totals


def _sum_overdue_retention_breach_age_bucket_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        bucket = scope.get("overdue_retention_breach_age_bucket")
        if not isinstance(bucket, str):
            continue
        totals[bucket] = totals.get(bucket, 0) + 1
    return totals


def _sum_overdue_retention_breach_action_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        action = scope.get("overdue_retention_breach_action")
        if not isinstance(action, str):
            continue
        totals[action] = totals.get(action, 0) + 1
    return totals


def _sum_overdue_retention_breach_lane_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        lane = scope.get("overdue_retention_breach_lane")
        if not isinstance(lane, str):
            continue
        totals[lane] = totals.get(lane, 0) + 1
    return totals


def _sum_overdue_retention_breach_owner_target_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        owner_target = scope.get("overdue_retention_breach_owner_target")
        if not isinstance(owner_target, str):
            continue
        totals[owner_target] = totals.get(owner_target, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        mode = scope.get("overdue_retention_breach_follow_through_mode")
        if not isinstance(mode, str):
            continue
        totals[mode] = totals.get(mode, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get("overdue_retention_breach_follow_through_outcome")
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_completion_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_completion_state")
        if not isinstance(state, str):
            continue
        totals[state] = totals.get(state, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_verification_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_verification_state")
        if not isinstance(state, str):
            continue
        totals[state] = totals.get(state, 0) + 1
    return totals


def _sum_overdue_retention_breach_follow_through_verification_outcome_counts(
    scopes: list[dict[str, object]],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for scope in scopes:
        outcome = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome"
        )
        if not isinstance(outcome, str):
            continue
        totals[outcome] = totals.get(outcome, 0) + 1
    return totals


def _highest_priority_action_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        hint = scope.get("action_hint")
        priority = scope.get("action_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("action_target_memory_id")
        reasons = scope.get("action_reasons")
        if not (
            isinstance(hint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "action_hint": hint,
            "action_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "action_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["action_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_escalation_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        recommendation = scope.get("escalation_recommendation")
        priority = scope.get("escalation_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("escalation_target_memory_id")
        reasons = scope.get("escalation_reasons")
        if not (
            isinstance(recommendation, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "escalation_recommendation": recommendation,
            "escalation_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "escalation_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["escalation_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_follow_up_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        window = scope.get("follow_up_window")
        priority = scope.get("follow_up_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("follow_up_due_at")
        target_memory_id = scope.get("follow_up_target_memory_id")
        reasons = scope.get("follow_up_reasons")
        if not (
            isinstance(window, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "follow_up_window": window,
            "follow_up_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "follow_up_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["follow_up_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        priority = scope.get("follow_up_overdue_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        overdue_since = scope.get("follow_up_overdue_since")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("follow_up_overdue_reasons")
        if not (
            overdue is True
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(overdue_since, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "follow_up_overdue_priority": priority,
            "follow_up_overdue_since": overdue_since,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "follow_up_overdue_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["follow_up_overdue_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_age_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        bucket = scope.get("overdue_age_bucket")
        age_seconds = scope.get("overdue_age_seconds")
        age_days = scope.get("overdue_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("overdue_age_reasons")
        if not (
            overdue is True
            and isinstance(bucket, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_age_bucket": bucket,
            "overdue_age_seconds": age_seconds,
            "overdue_age_days": age_days,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_age_reasons": [reason for reason in reasons if isinstance(reason, str)],
        }
        if highest is None or _overdue_age_bucket_rank(bucket) > _overdue_age_bucket_rank(
            str(highest["overdue_age_bucket"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_type_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        memory_type = scope.get("highest_overdue_memory_type")
        count = scope.get("highest_overdue_memory_type_count")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        target_memory_type = scope.get("overdue_target_memory_type")
        reasons = scope.get("overdue_type_rollup_reasons")
        if not (
            overdue is True
            and isinstance(memory_type, str)
            and isinstance(count, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "highest_overdue_memory_type": memory_type,
            "highest_overdue_memory_type_count": count,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_target_memory_type": (
                target_memory_type if isinstance(target_memory_type, str) else None
            ),
            "overdue_type_rollup_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None:
            highest = candidate
            continue
        highest_count = cast(int, highest["highest_overdue_memory_type_count"])
        highest_type = highest["highest_overdue_memory_type"]
        if count > highest_count or (
            count == highest_count and memory_type < str(highest_type)
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_visibility_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        visibility = scope.get("highest_overdue_memory_visibility")
        count = scope.get("highest_overdue_memory_visibility_count")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        target_memory_visibility = scope.get("overdue_target_memory_visibility")
        reasons = scope.get("overdue_visibility_rollup_reasons")
        if not (
            overdue is True
            and isinstance(visibility, str)
            and isinstance(count, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "highest_overdue_memory_visibility": visibility,
            "highest_overdue_memory_visibility_count": count,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_target_memory_visibility": (
                target_memory_visibility
                if isinstance(target_memory_visibility, str)
                else None
            ),
            "overdue_visibility_rollup_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None:
            highest = candidate
            continue
        highest_count = cast(int, highest["highest_overdue_memory_visibility_count"])
        highest_visibility = highest["highest_overdue_memory_visibility"]
        if count > highest_count or (
            count == highest_count and visibility < str(highest_visibility)
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_trend_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        signal = scope.get("overdue_trend_signal")
        rank = scope.get("overdue_trend_rank")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("follow_up_overdue_target_memory_id")
        reasons = scope.get("overdue_trend_reasons")
        if not (
            overdue is True
            and isinstance(signal, str)
            and isinstance(rank, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_trend_signal": signal,
            "overdue_trend_rank": rank,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_trend_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None:
            highest = candidate
            continue
        highest_rank = cast(int, highest["overdue_trend_rank"])
        highest_signal = highest["overdue_trend_signal"]
        if rank > highest_rank or (rank == highest_rank and signal < str(highest_signal)):
            highest = candidate
    return highest


def _highest_priority_overdue_intervention_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        hint = scope.get("overdue_intervention_hint")
        priority = scope.get("overdue_intervention_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_intervention_target_memory_id")
        reasons = scope.get("overdue_intervention_reasons")
        if not (
            overdue is True
            and isinstance(hint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_intervention_hint": hint,
            "overdue_intervention_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_intervention_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_intervention_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_escalation_lane_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        lane = scope.get("overdue_escalation_lane")
        priority = scope.get("overdue_escalation_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_escalation_target_memory_id")
        reasons = scope.get("overdue_escalation_reasons")
        if not (
            overdue is True
            and isinstance(lane, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_escalation_lane": lane,
            "overdue_escalation_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_escalation_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_escalation_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_recovery_path_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        path = scope.get("overdue_recovery_path")
        priority = scope.get("overdue_recovery_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_recovery_target_memory_id")
        reasons = scope.get("overdue_recovery_reasons")
        if not (
            overdue is True
            and isinstance(path, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_recovery_path": path,
            "overdue_recovery_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_recovery_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_recovery_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_resolution_checkpoint_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        checkpoint = scope.get("overdue_resolution_checkpoint")
        priority = scope.get("overdue_resolution_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_resolution_target_memory_id")
        reasons = scope.get("overdue_resolution_reasons")
        if not (
            overdue is True
            and isinstance(checkpoint, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_resolution_checkpoint": checkpoint,
            "overdue_resolution_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_resolution_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_resolution_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_resolution_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        outcome = scope.get("overdue_resolution_outcome")
        priority = scope.get("overdue_resolution_outcome_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_resolution_outcome_target_memory_id")
        reasons = scope.get("overdue_resolution_outcome_reasons")
        if not (
            overdue is True
            and isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_resolution_outcome": outcome,
            "overdue_resolution_outcome_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_resolution_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_resolution_outcome_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_closure_decision_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        decision = scope.get("overdue_closure_decision")
        priority = scope.get("overdue_closure_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_closure_target_memory_id")
        reasons = scope.get("overdue_closure_reasons")
        if not (
            overdue is True
            and isinstance(decision, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_closure_decision": decision,
            "overdue_closure_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_closure_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_closure_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_archive_recommendation_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        recommendation = scope.get("overdue_archive_recommendation")
        priority = scope.get("overdue_archive_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_archive_target_memory_id")
        reasons = scope.get("overdue_archive_reasons")
        if not (
            overdue is True
            and isinstance(recommendation, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_archive_recommendation": recommendation,
            "overdue_archive_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_archive_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_archive_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_guidance_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        guidance = scope.get("overdue_retention_guidance")
        priority = scope.get("overdue_retention_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_target_memory_id")
        bucket = scope.get("overdue_retention_bucket")
        reasons = scope.get("overdue_retention_reasons")
        if not (
            overdue is True
            and isinstance(guidance, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(bucket, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_guidance": guidance,
            "overdue_retention_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_bucket": bucket,
            "overdue_retention_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_window_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        window = scope.get("overdue_retention_window")
        priority = scope.get("overdue_retention_window_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("overdue_retention_window_due_at")
        target_memory_id = scope.get("overdue_retention_window_target_memory_id")
        reasons = scope.get("overdue_retention_window_reasons")
        if not (
            overdue is True
            and isinstance(window, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_window": window,
            "overdue_retention_window_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_window_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_window_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        overdue = scope.get("follow_up_overdue")
        breach = scope.get("overdue_retention_breach")
        priority = scope.get("overdue_retention_breach_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        due_at = scope.get("overdue_retention_breach_due_at")
        target_memory_id = scope.get("overdue_retention_breach_target_memory_id")
        reasons = scope.get("overdue_retention_breach_reasons")
        if not (
            overdue is True
            and isinstance(breach, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(due_at, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach": breach,
            "overdue_retention_breach_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "due_at": due_at,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _action_priority_rank(priority) > _action_priority_rank(
            str(highest["overdue_retention_breach_priority"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_aging_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        bucket = scope.get("overdue_retention_breach_age_bucket")
        age_seconds = scope.get("overdue_retention_breach_age_seconds")
        age_days = scope.get("overdue_retention_breach_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        reasons = scope.get("overdue_retention_breach_age_reasons")
        if not (
            isinstance(bucket, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_age_bucket": bucket,
            "overdue_retention_breach_age_seconds": age_seconds,
            "overdue_retention_breach_age_days": age_days,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "overdue_retention_breach_age_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_age_bucket_rank(
            bucket
        ) > _overdue_retention_breach_age_bucket_rank(
            str(highest["overdue_retention_breach_age_bucket"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_action_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        action = scope.get("overdue_retention_breach_action")
        priority = scope.get("overdue_retention_breach_action_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_action_target_memory_id")
        reasons = scope.get("overdue_retention_breach_action_reasons")
        if not (
            isinstance(action, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_action": action,
            "overdue_retention_breach_action_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_action_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_action_rank(
            action
        ) > _overdue_retention_breach_action_rank(
            str(highest["overdue_retention_breach_action"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_lane_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        lane = scope.get("overdue_retention_breach_lane")
        priority = scope.get("overdue_retention_breach_lane_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_lane_target_memory_id")
        reasons = scope.get("overdue_retention_breach_lane_reasons")
        if not (
            isinstance(lane, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_lane": lane,
            "overdue_retention_breach_lane_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_lane_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_lane_rank(
            lane
        ) > _overdue_retention_breach_lane_rank(
            str(highest["overdue_retention_breach_lane"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_owner_target_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        owner_target = scope.get("overdue_retention_breach_owner_target")
        priority = scope.get("overdue_retention_breach_owner_target_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_owner_target_memory_id")
        reasons = scope.get("overdue_retention_breach_owner_target_reasons")
        if not (
            isinstance(owner_target, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_owner_target": owner_target,
            "overdue_retention_breach_owner_target_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_owner_target_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_owner_target_rank(
            owner_target
        ) > _overdue_retention_breach_owner_target_rank(
            str(highest["overdue_retention_breach_owner_target"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        mode = scope.get("overdue_retention_breach_follow_through_mode")
        priority = scope.get("overdue_retention_breach_follow_through_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get("overdue_retention_breach_follow_through_memory_id")
        reasons = scope.get("overdue_retention_breach_follow_through_reasons")
        if not (
            isinstance(mode, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_mode": mode,
            "overdue_retention_breach_follow_through_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_rank(
            mode
        ) > _overdue_retention_breach_follow_through_rank(
            str(highest["overdue_retention_breach_follow_through_mode"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        outcome = scope.get("overdue_retention_breach_follow_through_outcome")
        priority = scope.get("overdue_retention_breach_follow_through_outcome_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_outcome_memory_id"
        )
        reasons = scope.get("overdue_retention_breach_follow_through_outcome_reasons")
        if not (
            isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_outcome": outcome,
            "overdue_retention_breach_follow_through_outcome_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_outcome_rank(
            outcome
        ) > _overdue_retention_breach_follow_through_outcome_rank(
            str(highest["overdue_retention_breach_follow_through_outcome"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_completion_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_completion_state")
        priority = scope.get("overdue_retention_breach_follow_through_completion_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_completion_memory_id"
        )
        reasons = scope.get("overdue_retention_breach_follow_through_completion_reasons")
        if not (
            isinstance(state, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_completion_state": state,
            "overdue_retention_breach_follow_through_completion_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_completion_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_completion_rank(
            state
        ) > _overdue_retention_breach_follow_through_completion_rank(
            str(highest["overdue_retention_breach_follow_through_completion_state"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_verification_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        state = scope.get("overdue_retention_breach_follow_through_verification_state")
        priority = scope.get("overdue_retention_breach_follow_through_verification_priority")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_verification_memory_id"
        )
        reasons = scope.get("overdue_retention_breach_follow_through_verification_reasons")
        if not (
            isinstance(state, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_verification_state": state,
            "overdue_retention_breach_follow_through_verification_priority": priority,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_verification_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_verification_rank(
            state
        ) > _overdue_retention_breach_follow_through_verification_rank(
            str(highest["overdue_retention_breach_follow_through_verification_state"])
        ):
            highest = candidate
    return highest


def _highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    highest: dict[str, object] | None = None
    for scope in scopes:
        outcome = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome"
        )
        priority = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome_priority"
        )
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        target_memory_id = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome_memory_id"
        )
        reasons = scope.get(
            "overdue_retention_breach_follow_through_verification_outcome_reasons"
        )
        if not (
            isinstance(outcome, str)
            and isinstance(priority, str)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
            and isinstance(reasons, list)
        ):
            continue
        candidate: dict[str, object] = {
            "overdue_retention_breach_follow_through_verification_outcome": outcome,
            "overdue_retention_breach_follow_through_verification_outcome_priority": (
                priority
            ),
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "target_memory_id": (
                target_memory_id if isinstance(target_memory_id, str) else None
            ),
            "overdue_retention_breach_follow_through_verification_outcome_reasons": [
                reason for reason in reasons if isinstance(reason, str)
            ],
        }
        if highest is None or _overdue_retention_breach_follow_through_verification_outcome_rank(
            outcome
        ) > _overdue_retention_breach_follow_through_verification_outcome_rank(
            str(highest["overdue_retention_breach_follow_through_verification_outcome"])
        ):
            highest = candidate
    return highest


def _oldest_pending_scope(
    scopes: list[dict[str, object]],
) -> dict[str, object] | None:
    oldest: dict[str, object] | None = None
    for scope in scopes:
        captured_at = scope.get("oldest_pending_captured_at")
        memory_id = scope.get("oldest_pending_memory_id")
        age_seconds = scope.get("oldest_pending_age_seconds")
        age_days = scope.get("oldest_pending_age_days")
        scope_kind = scope.get("scope_kind")
        scope_id = scope.get("scope_id")
        if not (
            isinstance(captured_at, str)
            and isinstance(memory_id, str)
            and isinstance(age_seconds, int)
            and isinstance(age_days, int)
            and isinstance(scope_kind, str)
            and isinstance(scope_id, str)
        ):
            continue
        candidate = {
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "memory_id": memory_id,
            "captured_at": captured_at,
            "age_seconds": age_seconds,
            "age_days": age_days,
        }
        if oldest is None or captured_at < str(oldest["captured_at"]):
            oldest = candidate
    return oldest


def _pressure_rank(level: str) -> int:
    ranks = {
        "clear": 0,
        "steady": 1,
        "elevated": 2,
        "high": 3,
    }
    return ranks.get(level, -1)


def _overdue_age_bucket_rank(bucket: str) -> int:
    ranks = {
        "not_overdue": 0,
        "unknown_overdue_age": 0,
        "lt_1d_overdue": 1,
        "gte_1d_lt_3d_overdue": 2,
        "gte_3d_lt_7d_overdue": 3,
        "gte_7d_overdue": 4,
    }
    return ranks.get(bucket, -1)


def _overdue_retention_breach_age_bucket_rank(bucket: str) -> int:
    ranks = {
        "not_breached": 0,
        "unknown_breach_age": 0,
        "lt_1d_breached": 1,
        "gte_1d_lt_3d_breached": 2,
        "gte_3d_lt_7d_breached": 3,
        "gte_7d_breached": 4,
    }
    return ranks.get(bucket, -1)


def _overdue_retention_breach_action_rank(action: str) -> int:
    ranks = {
        "no_retention_action": 0,
        "inspect_breach_timestamps": 1,
        "queue_immediate_retention_review": 2,
        "assign_retention_owner": 3,
        "escalate_retention_decision": 4,
        "force_archive_or_override": 5,
    }
    return ranks.get(action, -1)


def _overdue_retention_breach_lane_rank(lane: str) -> int:
    ranks = {
        "no_retention_lane": 0,
        "operator_timestamp_review_lane": 1,
        "operator_retention_review_lane": 2,
        "owner_assignment_lane": 3,
        "manager_retention_escalation_lane": 4,
        "emergency_retention_override_lane": 5,
    }
    return ranks.get(lane, -1)


def _overdue_retention_breach_owner_target_rank(owner_target: str) -> int:
    ranks = {
        "no_owner_assignment": 0,
        "memory_operator": 1,
        "scope_owner": 2,
        "retention_manager": 3,
        "retention_admin": 4,
    }
    return ranks.get(owner_target, -1)


def _overdue_retention_breach_follow_through_rank(mode: str) -> int:
    ranks = {
        "no_follow_through_needed": 0,
        "operator_review_follow_through": 1,
        "owner_confirmation_follow_through": 2,
        "manager_decision_follow_through": 3,
        "admin_override_follow_through": 4,
    }
    return ranks.get(mode, -1)


def _overdue_retention_breach_follow_through_outcome_rank(outcome: str) -> int:
    ranks = {
        "no_follow_through_outstanding": 0,
        "follow_through_monitoring_only": 1,
        "awaiting_operator_follow_through": 2,
        "awaiting_owner_follow_through": 3,
        "awaiting_manager_follow_through": 4,
        "awaiting_admin_override_follow_through": 5,
    }
    return ranks.get(outcome, -1)


def _overdue_retention_breach_follow_through_completion_rank(state: str) -> int:
    ranks = {
        "completion_not_required": 0,
        "completion_monitoring_only": 1,
        "operator_completion_pending": 2,
        "owner_completion_pending": 3,
        "manager_completion_pending": 4,
        "admin_override_completion_pending": 5,
    }
    return ranks.get(state, -1)


def _overdue_retention_breach_follow_through_verification_rank(state: str) -> int:
    ranks = {
        "verification_not_required": 0,
        "verification_monitoring_only": 1,
        "operator_verification_pending": 2,
        "owner_verification_pending": 3,
        "manager_verification_pending": 4,
        "admin_override_verification_pending": 5,
    }
    return ranks.get(state, -1)


def _overdue_retention_breach_follow_through_verification_outcome_rank(
    outcome: str,
) -> int:
    ranks = {
        "verification_resolved": 0,
        "verification_monitoring_only": 1,
        "awaiting_operator_verification_outcome": 2,
        "awaiting_owner_verification_outcome": 3,
        "awaiting_manager_verification_outcome": 4,
        "awaiting_admin_override_verification_outcome": 5,
    }
    return ranks.get(outcome, -1)


def _action_priority_rank(priority: str) -> int:
    ranks = {
        "none": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
    }
    return ranks.get(priority, -1)


def _parse_as_of(value: str | None) -> datetime | dict[str, str] | None:
    if value is None:
        return None
    if not value.strip():
        return {"status": "invalid_request", "reason": "as_of must be a non-blank ISO 8601 string"}
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return {"status": "invalid_request", "reason": "as_of must be a valid ISO 8601 datetime"}
    if parsed.tzinfo is None:
        return {"status": "invalid_request", "reason": "as_of must include timezone information"}
    return parsed.astimezone(UTC)
