from __future__ import annotations

import argparse
from pathlib import Path

from zebra_agent_cli.approval_read import list_approvals, read_approval_detail
from zebra_agent_cli.cli_types import CliCommandResult, CommandName
from zebra_agent_cli.delivery_audit_read import read_delivery_audit
from zebra_agent_cli.session_diff_read import read_session_diff
from zebra_agent_cli.session_memory_read import (
    read_session_memory,
    read_session_memory_action_hints,
    read_session_memory_backlog_aging_signals,
    read_session_memory_backlog_pressure_signals,
    read_session_memory_escalations,
    read_session_memory_follow_up_windows,
    read_session_memory_governance_signals,
    read_session_memory_operations_overview,
    read_session_memory_overdue_age_buckets,
    read_session_memory_overdue_archive_recommendations,
    read_session_memory_overdue_closure_decisions,
    read_session_memory_overdue_escalation_lanes,
    read_session_memory_overdue_flags,
    read_session_memory_overdue_intervention_hints,
    read_session_memory_overdue_recovery_paths,
    read_session_memory_overdue_resolution_checkpoints,
    read_session_memory_overdue_resolution_outcomes,
    read_session_memory_overdue_retention_breach_actions,
    read_session_memory_overdue_retention_breach_aging,
    read_session_memory_overdue_retention_breach_follow_through_completion_states,
    read_session_memory_overdue_retention_breach_follow_through_modes,
    read_session_memory_overdue_retention_breach_follow_through_outcomes,
    read_session_memory_overdue_retention_breach_follow_through_verification_outcomes,
    read_session_memory_overdue_retention_breach_follow_through_verification_states,
    read_session_memory_overdue_retention_breach_lanes,
    read_session_memory_overdue_retention_breach_owner_targets,
    read_session_memory_overdue_retention_breaches,
    read_session_memory_overdue_retention_guidance,
    read_session_memory_overdue_retention_windows,
    read_session_memory_overdue_trend_signals,
    read_session_memory_overdue_type_rollups,
    read_session_memory_overdue_visibility_rollups,
    read_session_memory_queue,
    read_session_memory_queue_summary,
    read_session_memory_review_velocity_signals,
    read_tenant_memory,
    read_tenant_memory_queue,
    read_tenant_memory_queue_summary,
    read_user_memory,
    read_user_memory_queue,
    read_user_memory_queue_summary,
)
from zebra_agent_cli.session_stream_read import read_session_stream


def add_read_subparsers(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    approval = subcommands.add_parser(
        "approval",
        help="Inspect the waiting approval queue or one approval detail.",
    )
    approval_subcommands = approval.add_subparsers(dest="approval_command", required=True)
    approval_queue = approval_subcommands.add_parser(
        "queue",
        help="List waiting approvals from the local projection store.",
    )
    approval_queue.add_argument("--database")
    approval_inspect = approval_subcommands.add_parser(
        "inspect",
        help="Inspect one waiting approval from the local projection store.",
    )
    approval_inspect.add_argument("approval_id")
    approval_inspect.add_argument("--database")

    diff = subcommands.add_parser("diff", help="Read one session workspace diff.")
    diff.add_argument("session_id")
    diff.add_argument("--database")

    memory = subcommands.add_parser("memory", help="Read one session memory inventory.")
    memory.add_argument("session_id")
    memory.add_argument("--database")

    memory_action_hints = subcommands.add_parser(
        "memory-action-hints",
        help="Read one session memory pressure action hints overview.",
    )
    memory_action_hints.add_argument("session_id")
    memory_action_hints.add_argument("--user-id")
    memory_action_hints.add_argument("--tenant-id")
    memory_action_hints.add_argument("--as-of")
    memory_action_hints.add_argument("--database")

    memory_escalations = subcommands.add_parser(
        "memory-escalations",
        help="Read one session memory pressure escalation overview.",
    )
    memory_escalations.add_argument("session_id")
    memory_escalations.add_argument("--user-id")
    memory_escalations.add_argument("--tenant-id")
    memory_escalations.add_argument("--as-of")
    memory_escalations.add_argument("--database")

    memory_follow_up_windows = subcommands.add_parser(
        "memory-follow-up-windows",
        help="Read one session memory escalation follow-up overview.",
    )
    memory_follow_up_windows.add_argument("session_id")
    memory_follow_up_windows.add_argument("--user-id")
    memory_follow_up_windows.add_argument("--tenant-id")
    memory_follow_up_windows.add_argument("--as-of")
    memory_follow_up_windows.add_argument("--database")

    memory_overdue_flags = subcommands.add_parser(
        "memory-overdue-flags",
        help="Read one session memory follow-up overdue overview.",
    )
    memory_overdue_flags.add_argument("session_id")
    memory_overdue_flags.add_argument("--user-id")
    memory_overdue_flags.add_argument("--tenant-id")
    memory_overdue_flags.add_argument("--as-of")
    memory_overdue_flags.add_argument("--database")

    memory_overdue_age_buckets = subcommands.add_parser(
        "memory-overdue-age-buckets",
        help="Read one session memory overdue age overview.",
    )
    memory_overdue_age_buckets.add_argument("session_id")
    memory_overdue_age_buckets.add_argument("--user-id")
    memory_overdue_age_buckets.add_argument("--tenant-id")
    memory_overdue_age_buckets.add_argument("--as-of")
    memory_overdue_age_buckets.add_argument("--database")

    memory_overdue_types = subcommands.add_parser(
        "memory-overdue-types",
        help="Read one session memory overdue type overview.",
    )
    memory_overdue_types.add_argument("session_id")
    memory_overdue_types.add_argument("--user-id")
    memory_overdue_types.add_argument("--tenant-id")
    memory_overdue_types.add_argument("--as-of")
    memory_overdue_types.add_argument("--database")

    memory_overdue_visibility = subcommands.add_parser(
        "memory-overdue-visibility",
        help="Read one session memory overdue visibility overview.",
    )
    memory_overdue_visibility.add_argument("session_id")
    memory_overdue_visibility.add_argument("--user-id")
    memory_overdue_visibility.add_argument("--tenant-id")
    memory_overdue_visibility.add_argument("--as-of")
    memory_overdue_visibility.add_argument("--database")

    memory_overdue_trends = subcommands.add_parser(
        "memory-overdue-trends",
        help="Read one session memory overdue trend overview.",
    )
    memory_overdue_trends.add_argument("session_id")
    memory_overdue_trends.add_argument("--user-id")
    memory_overdue_trends.add_argument("--tenant-id")
    memory_overdue_trends.add_argument("--as-of")
    memory_overdue_trends.add_argument("--database")

    memory_overdue_interventions = subcommands.add_parser(
        "memory-overdue-interventions",
        help="Read one session memory overdue intervention overview.",
    )
    memory_overdue_interventions.add_argument("session_id")
    memory_overdue_interventions.add_argument("--user-id")
    memory_overdue_interventions.add_argument("--tenant-id")
    memory_overdue_interventions.add_argument("--as-of")
    memory_overdue_interventions.add_argument("--database")

    memory_overdue_escalation_lanes = subcommands.add_parser(
        "memory-overdue-escalation-lanes",
        help="Read one session memory overdue escalation lane overview.",
    )
    memory_overdue_escalation_lanes.add_argument("session_id")
    memory_overdue_escalation_lanes.add_argument("--user-id")
    memory_overdue_escalation_lanes.add_argument("--tenant-id")
    memory_overdue_escalation_lanes.add_argument("--as-of")
    memory_overdue_escalation_lanes.add_argument("--database")

    memory_overdue_recovery_paths = subcommands.add_parser(
        "memory-overdue-recovery-paths",
        help="Read one session memory overdue recovery path overview.",
    )
    memory_overdue_recovery_paths.add_argument("session_id")
    memory_overdue_recovery_paths.add_argument("--user-id")
    memory_overdue_recovery_paths.add_argument("--tenant-id")
    memory_overdue_recovery_paths.add_argument("--as-of")
    memory_overdue_recovery_paths.add_argument("--database")

    memory_overdue_resolution_checkpoints = subcommands.add_parser(
        "memory-overdue-resolution-checkpoints",
        help="Read one session memory overdue resolution checkpoint overview.",
    )
    memory_overdue_resolution_checkpoints.add_argument("session_id")
    memory_overdue_resolution_checkpoints.add_argument("--user-id")
    memory_overdue_resolution_checkpoints.add_argument("--tenant-id")
    memory_overdue_resolution_checkpoints.add_argument("--as-of")
    memory_overdue_resolution_checkpoints.add_argument("--database")

    memory_overdue_resolution_outcomes = subcommands.add_parser(
        "memory-overdue-resolution-outcomes",
        help="Read one session memory overdue resolution outcome overview.",
    )
    memory_overdue_resolution_outcomes.add_argument("session_id")
    memory_overdue_resolution_outcomes.add_argument("--user-id")
    memory_overdue_resolution_outcomes.add_argument("--tenant-id")
    memory_overdue_resolution_outcomes.add_argument("--as-of")
    memory_overdue_resolution_outcomes.add_argument("--database")

    memory_overdue_closure_decisions = subcommands.add_parser(
        "memory-overdue-closure-decisions",
        help="Read one session memory overdue closure decision overview.",
    )
    memory_overdue_closure_decisions.add_argument("session_id")
    memory_overdue_closure_decisions.add_argument("--user-id")
    memory_overdue_closure_decisions.add_argument("--tenant-id")
    memory_overdue_closure_decisions.add_argument("--as-of")
    memory_overdue_closure_decisions.add_argument("--database")

    memory_overdue_archive_recommendations = subcommands.add_parser(
        "memory-overdue-archive-recommendations",
        help="Read one session memory overdue archive recommendation overview.",
    )
    memory_overdue_archive_recommendations.add_argument("session_id")
    memory_overdue_archive_recommendations.add_argument("--user-id")
    memory_overdue_archive_recommendations.add_argument("--tenant-id")
    memory_overdue_archive_recommendations.add_argument("--as-of")
    memory_overdue_archive_recommendations.add_argument("--database")

    memory_overdue_retention_guidance = subcommands.add_parser(
        "memory-overdue-retention-guidance",
        help="Read one session memory overdue retention guidance overview.",
    )
    memory_overdue_retention_guidance.add_argument("session_id")
    memory_overdue_retention_guidance.add_argument("--user-id")
    memory_overdue_retention_guidance.add_argument("--tenant-id")
    memory_overdue_retention_guidance.add_argument("--as-of")
    memory_overdue_retention_guidance.add_argument("--database")

    memory_overdue_retention_windows = subcommands.add_parser(
        "memory-overdue-retention-windows",
        help="Read one session memory overdue retention window overview.",
    )
    memory_overdue_retention_windows.add_argument("session_id")
    memory_overdue_retention_windows.add_argument("--user-id")
    memory_overdue_retention_windows.add_argument("--tenant-id")
    memory_overdue_retention_windows.add_argument("--as-of")
    memory_overdue_retention_windows.add_argument("--database")

    memory_overdue_retention_breaches = subcommands.add_parser(
        "memory-overdue-retention-breaches",
        help="Read one session memory overdue retention breach overview.",
    )
    memory_overdue_retention_breaches.add_argument("session_id")
    memory_overdue_retention_breaches.add_argument("--user-id")
    memory_overdue_retention_breaches.add_argument("--tenant-id")
    memory_overdue_retention_breaches.add_argument("--as-of")
    memory_overdue_retention_breaches.add_argument("--database")

    memory_overdue_retention_breach_aging = subcommands.add_parser(
        "memory-overdue-retention-breach-aging",
        help="Read one session memory overdue retention breach aging overview.",
    )
    memory_overdue_retention_breach_aging.add_argument("session_id")
    memory_overdue_retention_breach_aging.add_argument("--user-id")
    memory_overdue_retention_breach_aging.add_argument("--tenant-id")
    memory_overdue_retention_breach_aging.add_argument("--as-of")
    memory_overdue_retention_breach_aging.add_argument("--database")

    memory_overdue_retention_breach_actions = subcommands.add_parser(
        "memory-overdue-retention-breach-actions",
        help="Read one session memory overdue retention breach action overview.",
    )
    memory_overdue_retention_breach_actions.add_argument("session_id")
    memory_overdue_retention_breach_actions.add_argument("--user-id")
    memory_overdue_retention_breach_actions.add_argument("--tenant-id")
    memory_overdue_retention_breach_actions.add_argument("--as-of")
    memory_overdue_retention_breach_actions.add_argument("--database")

    memory_overdue_retention_breach_lanes = subcommands.add_parser(
        "memory-overdue-retention-breach-lanes",
        help="Read one session memory overdue retention breach lane overview.",
    )
    memory_overdue_retention_breach_lanes.add_argument("session_id")
    memory_overdue_retention_breach_lanes.add_argument("--user-id")
    memory_overdue_retention_breach_lanes.add_argument("--tenant-id")
    memory_overdue_retention_breach_lanes.add_argument("--as-of")
    memory_overdue_retention_breach_lanes.add_argument("--database")

    memory_overdue_retention_breach_owner_targets = subcommands.add_parser(
        "memory-overdue-retention-breach-owner-targets",
        help="Read one session memory overdue retention breach owner target overview.",
    )
    memory_overdue_retention_breach_owner_targets.add_argument("session_id")
    memory_overdue_retention_breach_owner_targets.add_argument("--user-id")
    memory_overdue_retention_breach_owner_targets.add_argument("--tenant-id")
    memory_overdue_retention_breach_owner_targets.add_argument("--as-of")
    memory_overdue_retention_breach_owner_targets.add_argument("--database")

    memory_overdue_retention_breach_follow_through_modes = subcommands.add_parser(
        "memory-overdue-retention-breach-follow-through-modes",
        help="Read one session memory overdue retention breach follow-through mode overview.",
    )
    memory_overdue_retention_breach_follow_through_modes.add_argument("session_id")
    memory_overdue_retention_breach_follow_through_modes.add_argument("--user-id")
    memory_overdue_retention_breach_follow_through_modes.add_argument("--tenant-id")
    memory_overdue_retention_breach_follow_through_modes.add_argument("--as-of")
    memory_overdue_retention_breach_follow_through_modes.add_argument("--database")

    memory_overdue_retention_breach_follow_through_outcomes = subcommands.add_parser(
        "memory-overdue-retention-breach-follow-through-outcomes",
        help="Read one session memory overdue retention breach follow-through outcome overview.",
    )
    memory_overdue_retention_breach_follow_through_outcomes.add_argument("session_id")
    memory_overdue_retention_breach_follow_through_outcomes.add_argument("--user-id")
    memory_overdue_retention_breach_follow_through_outcomes.add_argument("--tenant-id")
    memory_overdue_retention_breach_follow_through_outcomes.add_argument("--as-of")
    memory_overdue_retention_breach_follow_through_outcomes.add_argument("--database")

    memory_overdue_retention_breach_follow_through_completion_states = (
        subcommands.add_parser(
            "memory-overdue-retention-breach-follow-through-completion-states",
            help=(
                "Read one session memory overdue retention breach "
                "follow-through completion overview."
            ),
        )
    )
    memory_overdue_retention_breach_follow_through_completion_states.add_argument(
        "session_id"
    )
    memory_overdue_retention_breach_follow_through_completion_states.add_argument(
        "--user-id"
    )
    memory_overdue_retention_breach_follow_through_completion_states.add_argument(
        "--tenant-id"
    )
    memory_overdue_retention_breach_follow_through_completion_states.add_argument(
        "--as-of"
    )
    memory_overdue_retention_breach_follow_through_completion_states.add_argument(
        "--database"
    )

    memory_overdue_retention_breach_follow_through_verification_states = (
        subcommands.add_parser(
            "memory-overdue-retention-breach-follow-through-verification-states",
            help=(
                "Read one session memory overdue retention breach "
                "follow-through verification overview."
            ),
        )
    )
    memory_overdue_retention_breach_follow_through_verification_states.add_argument(
        "session_id"
    )
    memory_overdue_retention_breach_follow_through_verification_states.add_argument(
        "--user-id"
    )
    memory_overdue_retention_breach_follow_through_verification_states.add_argument(
        "--tenant-id"
    )
    memory_overdue_retention_breach_follow_through_verification_states.add_argument(
        "--as-of"
    )
    memory_overdue_retention_breach_follow_through_verification_states.add_argument(
        "--database"
    )

    memory_overdue_retention_breach_follow_through_verification_outcomes = (
        subcommands.add_parser(
            "memory-overdue-retention-breach-follow-through-verification-outcomes",
            help=(
                "Read one session memory overdue retention breach "
                "follow-through verification outcome overview."
            ),
        )
    )
    memory_overdue_retention_breach_follow_through_verification_outcomes.add_argument(
        "session_id"
    )
    memory_overdue_retention_breach_follow_through_verification_outcomes.add_argument(
        "--user-id"
    )
    memory_overdue_retention_breach_follow_through_verification_outcomes.add_argument(
        "--tenant-id"
    )
    memory_overdue_retention_breach_follow_through_verification_outcomes.add_argument(
        "--as-of"
    )
    memory_overdue_retention_breach_follow_through_verification_outcomes.add_argument(
        "--database"
    )

    memory_aging = subcommands.add_parser(
        "memory-aging",
        help="Read one session memory backlog aging overview.",
    )
    memory_aging.add_argument("session_id")
    memory_aging.add_argument("--user-id")
    memory_aging.add_argument("--tenant-id")
    memory_aging.add_argument("--as-of")
    memory_aging.add_argument("--database")

    memory_governance = subcommands.add_parser(
        "memory-governance",
        help="Read one session memory governance signal overview.",
    )
    memory_governance.add_argument("session_id")
    memory_governance.add_argument("--user-id")
    memory_governance.add_argument("--tenant-id")
    memory_governance.add_argument("--database")

    memory_velocity = subcommands.add_parser(
        "memory-velocity",
        help="Read one session memory review velocity overview.",
    )
    memory_velocity.add_argument("session_id")
    memory_velocity.add_argument("--user-id")
    memory_velocity.add_argument("--tenant-id")
    memory_velocity.add_argument("--as-of")
    memory_velocity.add_argument("--database")

    memory_pressure = subcommands.add_parser(
        "memory-pressure",
        help="Read one session memory backlog pressure overview.",
    )
    memory_pressure.add_argument("session_id")
    memory_pressure.add_argument("--user-id")
    memory_pressure.add_argument("--tenant-id")
    memory_pressure.add_argument("--as-of")
    memory_pressure.add_argument("--database")

    memory_overview = subcommands.add_parser(
        "memory-overview",
        help="Read one combined session memory operations overview.",
    )
    memory_overview.add_argument("session_id")
    memory_overview.add_argument("--user-id")
    memory_overview.add_argument("--tenant-id")
    memory_overview.add_argument("--database")

    memory_queue = subcommands.add_parser(
        "memory-queue",
        help="Read one session memory review queue.",
    )
    memory_queue.add_argument("session_id")
    memory_queue.add_argument("--database")

    memory_queue_summary = subcommands.add_parser(
        "memory-queue-summary",
        help="Read one session memory review queue summary.",
    )
    memory_queue_summary.add_argument("session_id")
    memory_queue_summary.add_argument("--database")

    memory_user = subcommands.add_parser(
        "memory-user",
        help="Read one user-scoped memory inventory.",
    )
    memory_user.add_argument("user_id")
    memory_user.add_argument("--database")

    memory_user_queue = subcommands.add_parser(
        "memory-user-queue",
        help="Read one user-scoped memory review queue.",
    )
    memory_user_queue.add_argument("user_id")
    memory_user_queue.add_argument("--database")

    memory_user_queue_summary = subcommands.add_parser(
        "memory-user-queue-summary",
        help="Read one user-scoped memory review queue summary.",
    )
    memory_user_queue_summary.add_argument("user_id")
    memory_user_queue_summary.add_argument("--database")

    memory_tenant = subcommands.add_parser(
        "memory-tenant",
        help="Read one tenant-scoped memory inventory.",
    )
    memory_tenant.add_argument("tenant_id")
    memory_tenant.add_argument("--database")

    memory_tenant_queue = subcommands.add_parser(
        "memory-tenant-queue",
        help="Read one tenant-scoped memory review queue.",
    )
    memory_tenant_queue.add_argument("tenant_id")
    memory_tenant_queue.add_argument("--database")

    memory_tenant_queue_summary = subcommands.add_parser(
        "memory-tenant-queue-summary",
        help="Read one tenant-scoped memory review queue summary.",
    )
    memory_tenant_queue_summary.add_argument("tenant_id")
    memory_tenant_queue_summary.add_argument("--database")

    stream = subcommands.add_parser("stream", help="Read one persisted session event stream.")
    stream.add_argument("session_id")
    stream.add_argument("--database")

    delivery_audit = subcommands.add_parser(
        "delivery-audit",
        help="Read one session delivery-audit history.",
    )
    delivery_audit.add_argument("session_id")
    delivery_audit.add_argument("--database")


def read_command_result(
    command: CommandName,
    *,
    database_path: Path,
    session_id: str | None = None,
    approval_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    as_of: str | None = None,
) -> CliCommandResult:
    if command == "approval":
        if approval_id is None:
            return CliCommandResult(
                command="approval",
                payload=list_approvals(database_path=database_path),
            )
        return CliCommandResult(
            command="approval",
            payload=read_approval_detail(
                database_path=database_path,
                approval_id=approval_id,
            ),
        )
    if command == "diff":
        assert session_id is not None
        return CliCommandResult(
            command="diff",
            payload=read_session_diff(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    if command == "memory":
        assert session_id is not None
        return CliCommandResult(
            command="memory",
            payload=read_session_memory(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    if command == "memory-action-hints":
        assert session_id is not None
        return CliCommandResult(
            command="memory-action-hints",
            payload=read_session_memory_action_hints(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-escalations":
        assert session_id is not None
        return CliCommandResult(
            command="memory-escalations",
            payload=read_session_memory_escalations(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-follow-up-windows":
        assert session_id is not None
        return CliCommandResult(
            command="memory-follow-up-windows",
            payload=read_session_memory_follow_up_windows(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-flags":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-flags",
            payload=read_session_memory_overdue_flags(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-age-buckets":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-age-buckets",
            payload=read_session_memory_overdue_age_buckets(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-types":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-types",
            payload=read_session_memory_overdue_type_rollups(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-visibility":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-visibility",
            payload=read_session_memory_overdue_visibility_rollups(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-trends":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-trends",
            payload=read_session_memory_overdue_trend_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-interventions":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-interventions",
            payload=read_session_memory_overdue_intervention_hints(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-escalation-lanes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-escalation-lanes",
            payload=read_session_memory_overdue_escalation_lanes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-recovery-paths":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-recovery-paths",
            payload=read_session_memory_overdue_recovery_paths(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-resolution-checkpoints":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-resolution-checkpoints",
            payload=read_session_memory_overdue_resolution_checkpoints(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-resolution-outcomes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-resolution-outcomes",
            payload=read_session_memory_overdue_resolution_outcomes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-closure-decisions":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-closure-decisions",
            payload=read_session_memory_overdue_closure_decisions(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-archive-recommendations":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-archive-recommendations",
            payload=read_session_memory_overdue_archive_recommendations(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-guidance":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-guidance",
            payload=read_session_memory_overdue_retention_guidance(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-windows":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-windows",
            payload=read_session_memory_overdue_retention_windows(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-breaches":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breaches",
            payload=read_session_memory_overdue_retention_breaches(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-breach-aging":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-aging",
            payload=read_session_memory_overdue_retention_breach_aging(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-breach-actions":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-actions",
            payload=read_session_memory_overdue_retention_breach_actions(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-breach-lanes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-lanes",
            payload=read_session_memory_overdue_retention_breach_lanes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-breach-owner-targets":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-owner-targets",
            payload=read_session_memory_overdue_retention_breach_owner_targets(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-breach-follow-through-modes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-modes",
            payload=read_session_memory_overdue_retention_breach_follow_through_modes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-breach-follow-through-outcomes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-outcomes",
            payload=read_session_memory_overdue_retention_breach_follow_through_outcomes(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overdue-retention-breach-follow-through-completion-states":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-completion-states",
            payload=(
                read_session_memory_overdue_retention_breach_follow_through_completion_states(
                    database_path=database_path,
                    session_id=session_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    as_of=as_of,
                )
            ),
        )
    if command == "memory-overdue-retention-breach-follow-through-verification-states":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-verification-states",
            payload=(
                read_session_memory_overdue_retention_breach_follow_through_verification_states(
                    database_path=database_path,
                    session_id=session_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    as_of=as_of,
                )
            ),
        )
    if command == "memory-overdue-retention-breach-follow-through-verification-outcomes":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overdue-retention-breach-follow-through-verification-outcomes",
            payload=(
                read_session_memory_overdue_retention_breach_follow_through_verification_outcomes(
                    database_path=database_path,
                    session_id=session_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    as_of=as_of,
                )
            ),
        )
    if command == "memory-aging":
        assert session_id is not None
        return CliCommandResult(
            command="memory-aging",
            payload=read_session_memory_backlog_aging_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-governance":
        assert session_id is not None
        return CliCommandResult(
            command="memory-governance",
            payload=read_session_memory_governance_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
            ),
        )
    if command == "memory-velocity":
        assert session_id is not None
        return CliCommandResult(
            command="memory-velocity",
            payload=read_session_memory_review_velocity_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-pressure":
        assert session_id is not None
        return CliCommandResult(
            command="memory-pressure",
            payload=read_session_memory_backlog_pressure_signals(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                as_of=as_of,
            ),
        )
    if command == "memory-overview":
        assert session_id is not None
        return CliCommandResult(
            command="memory-overview",
            payload=read_session_memory_operations_overview(
                database_path=database_path,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
            ),
        )
    if command == "memory-queue":
        assert session_id is not None
        return CliCommandResult(
            command="memory-queue",
            payload=read_session_memory_queue(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    if command == "memory-queue-summary":
        assert session_id is not None
        return CliCommandResult(
            command="memory-queue-summary",
            payload=read_session_memory_queue_summary(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    if command == "memory-user":
        assert user_id is not None
        return CliCommandResult(
            command="memory-user",
            payload=read_user_memory(
                database_path=database_path,
                user_id=user_id,
            ),
        )
    if command == "memory-user-queue":
        assert user_id is not None
        return CliCommandResult(
            command="memory-user-queue",
            payload=read_user_memory_queue(
                database_path=database_path,
                user_id=user_id,
            ),
        )
    if command == "memory-user-queue-summary":
        assert user_id is not None
        return CliCommandResult(
            command="memory-user-queue-summary",
            payload=read_user_memory_queue_summary(
                database_path=database_path,
                user_id=user_id,
            ),
        )
    if command == "memory-tenant":
        assert tenant_id is not None
        return CliCommandResult(
            command="memory-tenant",
            payload=read_tenant_memory(
                database_path=database_path,
                tenant_id=tenant_id,
            ),
        )
    if command == "memory-tenant-queue":
        assert tenant_id is not None
        return CliCommandResult(
            command="memory-tenant-queue",
            payload=read_tenant_memory_queue(
                database_path=database_path,
                tenant_id=tenant_id,
            ),
        )
    if command == "memory-tenant-queue-summary":
        assert tenant_id is not None
        return CliCommandResult(
            command="memory-tenant-queue-summary",
            payload=read_tenant_memory_queue_summary(
                database_path=database_path,
                tenant_id=tenant_id,
            ),
        )
    if command == "stream":
        assert session_id is not None
        return CliCommandResult(
            command="stream",
            payload=read_session_stream(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    if command == "delivery-audit":
        assert session_id is not None
        return CliCommandResult(
            command="delivery-audit",
            payload=read_delivery_audit(
                database_path=database_path,
                session_id=session_id,
            ),
        )
    raise ValueError(f"unsupported read command: {command}")
