from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zebra_agent_api.scoped_memory_read_mixin import ScopedMemoryReadMixin
from zebra_agent_api.session_artifact_read_mixin import SessionArtifactReadMixin
from zebra_agent_api.session_identity_read import (
    _parse_session_id,
)
from zebra_agent_api.session_memory_breach_mixin import SessionMemoryBreachMixin
from zebra_agent_api.session_memory_follow_through_mixin import SessionMemoryFollowThroughMixin
from zebra_agent_api.session_memory_follow_through_priority_read import (
    _highest_priority_overdue_retention_breach_follow_through_completion_scope,
    _highest_priority_overdue_retention_breach_follow_through_outcome_scope,
    _highest_priority_overdue_retention_breach_follow_through_scope,
    _highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope,
    _highest_priority_overdue_retention_breach_follow_through_verification_scope,
)
from zebra_agent_api.session_memory_overdue_response_mixin import SessionMemoryOverdueResponseMixin
from zebra_agent_api.session_memory_overdue_status_mixin import SessionMemoryOverdueStatusMixin
from zebra_agent_api.session_memory_overview_aggregation import (
    _artifact_lifecycle,
    _highest_pressure_scope,
    _latest_review_scope,
    _pressure_rank,
    _sum_action_hint_counts,
    _sum_age_bucket_counts,
    _sum_escalation_recommendation_counts,
    _sum_follow_up_window_counts,
    _sum_overdue_age_bucket_counts,
    _sum_overdue_escalation_lane_counts,
    _sum_overdue_intervention_hint_counts,
    _sum_overdue_memory_type_counts,
    _sum_overdue_memory_visibility_counts,
    _sum_overdue_recovery_path_counts,
    _sum_overdue_resolution_checkpoint_counts,
    _sum_overdue_resolution_outcome_counts,
    _sum_overdue_scope_count,
    _sum_overdue_trend_signal_counts,
    _sum_pending_counts,
    _sum_pressure_level_counts,
    _sum_recent_review_counts,
    _sum_reviewed_counts,
    _sum_status_counts,
)
from zebra_agent_api.session_memory_overview_mixin import SessionMemoryOverviewMixin
from zebra_agent_api.session_memory_pressure_mixin import SessionMemoryPressureMixin
from zebra_agent_api.session_memory_priority_read import (
    _highest_priority_action_scope,
    _highest_priority_escalation_scope,
    _highest_priority_follow_up_scope,
    _highest_priority_overdue_age_scope,
    _highest_priority_overdue_intervention_scope,
    _highest_priority_overdue_scope,
    _highest_priority_overdue_trend_scope,
    _highest_priority_overdue_type_scope,
    _highest_priority_overdue_visibility_scope,
)
from zebra_agent_api.session_memory_ranking import (
    _action_priority_rank,
    _oldest_pending_scope,
    _overdue_age_bucket_rank,
    _overdue_retention_breach_action_rank,
    _overdue_retention_breach_age_bucket_rank,
    _overdue_retention_breach_follow_through_completion_rank,
    _overdue_retention_breach_follow_through_outcome_rank,
    _overdue_retention_breach_follow_through_rank,
    _overdue_retention_breach_follow_through_verification_outcome_rank,
    _overdue_retention_breach_follow_through_verification_rank,
    _overdue_retention_breach_lane_rank,
    _overdue_retention_breach_owner_target_rank,
)
from zebra_agent_api.session_memory_resolution_mixin import SessionMemoryResolutionMixin
from zebra_agent_api.session_memory_resolution_priority_read import (
    _highest_priority_overdue_archive_recommendation_scope,
    _highest_priority_overdue_closure_decision_scope,
    _highest_priority_overdue_escalation_lane_scope,
    _highest_priority_overdue_recovery_path_scope,
    _highest_priority_overdue_resolution_checkpoint_scope,
    _highest_priority_overdue_resolution_outcome_scope,
    _highest_priority_overdue_retention_guidance_scope,
)
from zebra_agent_api.session_memory_retention_aggregation import (
    _sum_overdue_archive_recommendation_counts,
    _sum_overdue_closure_decision_counts,
    _sum_overdue_retention_breach_action_counts,
    _sum_overdue_retention_breach_age_bucket_counts,
    _sum_overdue_retention_breach_counts,
    _sum_overdue_retention_breach_follow_through_completion_counts,
    _sum_overdue_retention_breach_follow_through_counts,
    _sum_overdue_retention_breach_follow_through_outcome_counts,
    _sum_overdue_retention_breach_follow_through_verification_counts,
    _sum_overdue_retention_breach_follow_through_verification_outcome_counts,
    _sum_overdue_retention_breach_lane_counts,
    _sum_overdue_retention_breach_owner_target_counts,
    _sum_overdue_retention_guidance_counts,
    _sum_overdue_retention_window_counts,
)
from zebra_agent_api.session_memory_retention_mixin import SessionMemoryRetentionMixin
from zebra_agent_api.session_memory_retention_priority_read import (
    _highest_priority_overdue_retention_breach_action_scope,
    _highest_priority_overdue_retention_breach_aging_scope,
    _highest_priority_overdue_retention_breach_lane_scope,
    _highest_priority_overdue_retention_breach_owner_target_scope,
    _highest_priority_overdue_retention_breach_scope,
    _highest_priority_overdue_retention_window_scope,
)
from zebra_agent_api.session_state_read_mixin import SessionStateReadMixin


@dataclass(frozen=True)
class SessionReadApi(
    SessionStateReadMixin,
    SessionMemoryOverviewMixin,
    SessionMemoryPressureMixin,
    SessionMemoryOverdueStatusMixin,
    SessionMemoryOverdueResponseMixin,
    SessionMemoryResolutionMixin,
    SessionMemoryRetentionMixin,
    SessionMemoryBreachMixin,
    SessionMemoryFollowThroughMixin,
    ScopedMemoryReadMixin,
    SessionArtifactReadMixin,
):
    database_path: Path


__all__ = (
    "SessionReadApi",
    "_parse_session_id",
    "_artifact_lifecycle",
    "_sum_pending_counts",
    "_sum_reviewed_counts",
    "_sum_status_counts",
    "_sum_age_bucket_counts",
    "_sum_recent_review_counts",
    "_latest_review_scope",
    "_sum_pressure_level_counts",
    "_highest_pressure_scope",
    "_pressure_rank",
    "_sum_action_hint_counts",
    "_sum_escalation_recommendation_counts",
    "_sum_follow_up_window_counts",
    "_sum_overdue_scope_count",
    "_sum_overdue_age_bucket_counts",
    "_sum_overdue_memory_type_counts",
    "_sum_overdue_memory_visibility_counts",
    "_sum_overdue_trend_signal_counts",
    "_sum_overdue_intervention_hint_counts",
    "_sum_overdue_escalation_lane_counts",
    "_sum_overdue_recovery_path_counts",
    "_sum_overdue_resolution_checkpoint_counts",
    "_sum_overdue_resolution_outcome_counts",
    "_sum_overdue_closure_decision_counts",
    "_sum_overdue_archive_recommendation_counts",
    "_sum_overdue_retention_guidance_counts",
    "_sum_overdue_retention_window_counts",
    "_sum_overdue_retention_breach_counts",
    "_sum_overdue_retention_breach_age_bucket_counts",
    "_sum_overdue_retention_breach_action_counts",
    "_sum_overdue_retention_breach_lane_counts",
    "_sum_overdue_retention_breach_owner_target_counts",
    "_sum_overdue_retention_breach_follow_through_counts",
    "_sum_overdue_retention_breach_follow_through_outcome_counts",
    "_sum_overdue_retention_breach_follow_through_completion_counts",
    "_sum_overdue_retention_breach_follow_through_verification_counts",
    "_sum_overdue_retention_breach_follow_through_verification_outcome_counts",
    "_highest_priority_action_scope",
    "_highest_priority_escalation_scope",
    "_highest_priority_follow_up_scope",
    "_highest_priority_overdue_scope",
    "_highest_priority_overdue_age_scope",
    "_highest_priority_overdue_type_scope",
    "_highest_priority_overdue_visibility_scope",
    "_highest_priority_overdue_trend_scope",
    "_highest_priority_overdue_intervention_scope",
    "_highest_priority_overdue_escalation_lane_scope",
    "_highest_priority_overdue_recovery_path_scope",
    "_highest_priority_overdue_resolution_checkpoint_scope",
    "_highest_priority_overdue_resolution_outcome_scope",
    "_highest_priority_overdue_closure_decision_scope",
    "_highest_priority_overdue_archive_recommendation_scope",
    "_highest_priority_overdue_retention_guidance_scope",
    "_highest_priority_overdue_retention_window_scope",
    "_highest_priority_overdue_retention_breach_scope",
    "_highest_priority_overdue_retention_breach_aging_scope",
    "_highest_priority_overdue_retention_breach_action_scope",
    "_highest_priority_overdue_retention_breach_lane_scope",
    "_highest_priority_overdue_retention_breach_owner_target_scope",
    "_highest_priority_overdue_retention_breach_follow_through_scope",
    "_highest_priority_overdue_retention_breach_follow_through_outcome_scope",
    "_highest_priority_overdue_retention_breach_follow_through_completion_scope",
    "_highest_priority_overdue_retention_breach_follow_through_verification_scope",
    "_highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope",
    "_action_priority_rank",
    "_overdue_age_bucket_rank",
    "_overdue_retention_breach_age_bucket_rank",
    "_overdue_retention_breach_action_rank",
    "_overdue_retention_breach_lane_rank",
    "_overdue_retention_breach_owner_target_rank",
    "_overdue_retention_breach_follow_through_rank",
    "_overdue_retention_breach_follow_through_outcome_rank",
    "_overdue_retention_breach_follow_through_completion_rank",
    "_overdue_retention_breach_follow_through_verification_rank",
    "_overdue_retention_breach_follow_through_verification_outcome_rank",
    "_oldest_pending_scope",
)
