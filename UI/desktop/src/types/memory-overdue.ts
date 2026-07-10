import type { MemoryFollowUpScopeSignal } from "./memory";

export interface MemoryOverdueScopeSignal extends MemoryFollowUpScopeSignal {
  follow_up_overdue: boolean;
  follow_up_overdue_priority: string;
  follow_up_overdue_since: string | null;
  follow_up_overdue_target_memory_id: string | null;
  follow_up_overdue_reasons: string[];
}

export interface MemoryOverdueFlagsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  highest_priority_overdue_scope_kind: string | null;
  highest_priority_overdue_scope_id: string | null;
  highest_priority_overdue_priority: string | null;
  highest_priority_overdue_since: string | null;
  highest_priority_overdue_target_memory_id: string | null;
  highest_priority_overdue_reasons: string[];
  scopes: MemoryOverdueScopeSignal[];
}

export interface MemoryOverdueAgeScopeSignal extends MemoryOverdueScopeSignal {
  overdue_age_bucket: string;
  overdue_age_seconds: number | null;
  overdue_age_days: number | null;
  overdue_age_reasons: string[];
}

export interface MemoryOverdueAgeBucketsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_age_bucket_counts: Record<string, number>;
  highest_priority_overdue_age_bucket: string | null;
  highest_priority_overdue_age_scope_kind: string | null;
  highest_priority_overdue_age_scope_id: string | null;
  highest_priority_overdue_age_seconds: number | null;
  highest_priority_overdue_age_days: number | null;
  highest_priority_overdue_age_target_memory_id: string | null;
  highest_priority_overdue_age_reasons: string[];
  scopes: MemoryOverdueAgeScopeSignal[];
}

export interface MemoryOverdueTypeScopeSignal extends MemoryOverdueAgeScopeSignal {
  overdue_memory_count: number;
  overdue_memory_type_counts: Record<string, number>;
  highest_overdue_memory_type: string | null;
  highest_overdue_memory_type_count: number | null;
  overdue_target_memory_type: string | null;
  overdue_type_rollup_reasons: string[];
}

export interface MemoryOverdueTypeRollupsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_memory_type_counts: Record<string, number>;
  highest_priority_overdue_memory_type: string | null;
  highest_priority_overdue_memory_type_count: number | null;
  highest_priority_overdue_type_scope_kind: string | null;
  highest_priority_overdue_type_scope_id: string | null;
  highest_priority_overdue_type_target_memory_id: string | null;
  highest_priority_overdue_target_memory_type: string | null;
  highest_priority_overdue_type_reasons: string[];
  scopes: MemoryOverdueTypeScopeSignal[];
}

export interface MemoryOverdueVisibilityScopeSignal extends MemoryOverdueTypeScopeSignal {
  overdue_memory_visibility_counts: Record<string, number>;
  highest_overdue_memory_visibility: string | null;
  highest_overdue_memory_visibility_count: number | null;
  overdue_target_memory_visibility: string | null;
  overdue_visibility_rollup_reasons: string[];
}

export interface MemoryOverdueVisibilityRollupsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_memory_visibility_counts: Record<string, number>;
  highest_priority_overdue_memory_visibility: string | null;
  highest_priority_overdue_memory_visibility_count: number | null;
  highest_priority_overdue_visibility_scope_kind: string | null;
  highest_priority_overdue_visibility_scope_id: string | null;
  highest_priority_overdue_visibility_target_memory_id: string | null;
  highest_priority_overdue_target_memory_visibility: string | null;
  highest_priority_overdue_visibility_reasons: string[];
  scopes: MemoryOverdueVisibilityScopeSignal[];
}

export interface MemoryOverdueTrendScopeSignal extends MemoryOverdueVisibilityScopeSignal {
  overdue_trend_signal: string;
  overdue_trend_rank: number;
  overdue_trend_reasons: string[];
}

export interface MemoryOverdueTrendSignalsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_trend_signal_counts: Record<string, number>;
  highest_priority_overdue_trend_signal: string | null;
  highest_priority_overdue_trend_rank: number | null;
  highest_priority_overdue_trend_scope_kind: string | null;
  highest_priority_overdue_trend_scope_id: string | null;
  highest_priority_overdue_trend_target_memory_id: string | null;
  highest_priority_overdue_trend_reasons: string[];
  scopes: MemoryOverdueTrendScopeSignal[];
}

export interface MemoryOverdueInterventionScopeSignal extends MemoryOverdueTrendScopeSignal {
  overdue_intervention_hint: string;
  overdue_intervention_priority: string;
  overdue_intervention_target_memory_id: string | null;
  overdue_intervention_reasons: string[];
}

export interface MemoryOverdueInterventionsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_intervention_hint_counts: Record<string, number>;
  highest_priority_overdue_intervention_hint: string | null;
  highest_priority_overdue_intervention_priority: string | null;
  highest_priority_overdue_intervention_scope_kind: string | null;
  highest_priority_overdue_intervention_scope_id: string | null;
  highest_priority_overdue_intervention_target_memory_id: string | null;
  highest_priority_overdue_intervention_reasons: string[];
  scopes: MemoryOverdueInterventionScopeSignal[];
}

export interface MemoryOverdueEscalationLaneScopeSignal extends MemoryOverdueInterventionScopeSignal {
  overdue_escalation_lane: string;
  overdue_escalation_priority: string;
  overdue_escalation_target_memory_id: string | null;
  overdue_escalation_reasons: string[];
}

export interface MemoryOverdueEscalationLanesResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_escalation_lane_counts: Record<string, number>;
  highest_priority_overdue_escalation_lane: string | null;
  highest_priority_overdue_escalation_priority: string | null;
  highest_priority_overdue_escalation_scope_kind: string | null;
  highest_priority_overdue_escalation_scope_id: string | null;
  highest_priority_overdue_escalation_target_memory_id: string | null;
  highest_priority_overdue_escalation_reasons: string[];
  scopes: MemoryOverdueEscalationLaneScopeSignal[];
}

export interface MemoryOverdueRecoveryPathScopeSignal extends MemoryOverdueEscalationLaneScopeSignal {
  overdue_recovery_path: string;
  overdue_recovery_priority: string;
  overdue_recovery_target_memory_id: string | null;
  overdue_recovery_reasons: string[];
}

export interface MemoryOverdueRecoveryPathsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_recovery_path_counts: Record<string, number>;
  highest_priority_overdue_recovery_path: string | null;
  highest_priority_overdue_recovery_priority: string | null;
  highest_priority_overdue_recovery_scope_kind: string | null;
  highest_priority_overdue_recovery_scope_id: string | null;
  highest_priority_overdue_recovery_target_memory_id: string | null;
  highest_priority_overdue_recovery_reasons: string[];
  scopes: MemoryOverdueRecoveryPathScopeSignal[];
}

export interface MemoryOverdueResolutionCheckpointScopeSignal extends MemoryOverdueRecoveryPathScopeSignal {
  overdue_resolution_checkpoint: string;
  overdue_resolution_priority: string;
  overdue_resolution_target_memory_id: string | null;
  overdue_resolution_reasons: string[];
}

export interface MemoryOverdueResolutionCheckpointsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_resolution_checkpoint_counts: Record<string, number>;
  highest_priority_overdue_resolution_checkpoint: string | null;
  highest_priority_overdue_resolution_priority: string | null;
  highest_priority_overdue_resolution_scope_kind: string | null;
  highest_priority_overdue_resolution_scope_id: string | null;
  highest_priority_overdue_resolution_target_memory_id: string | null;
  highest_priority_overdue_resolution_reasons: string[];
  scopes: MemoryOverdueResolutionCheckpointScopeSignal[];
}

export interface MemoryOverdueResolutionOutcomeScopeSignal extends MemoryOverdueResolutionCheckpointScopeSignal {
  overdue_resolution_outcome: string;
  overdue_resolution_outcome_priority: string;
  overdue_resolution_outcome_target_memory_id: string | null;
  overdue_resolution_outcome_reasons: string[];
}

export interface MemoryOverdueResolutionOutcomesResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_resolution_outcome_counts: Record<string, number>;
  highest_priority_overdue_resolution_outcome: string | null;
  highest_priority_overdue_resolution_outcome_priority: string | null;
  highest_priority_overdue_resolution_outcome_scope_kind: string | null;
  highest_priority_overdue_resolution_outcome_scope_id: string | null;
  highest_priority_overdue_resolution_outcome_target_memory_id: string | null;
  highest_priority_overdue_resolution_outcome_reasons: string[];
  scopes: MemoryOverdueResolutionOutcomeScopeSignal[];
}

export interface MemoryOverdueClosureDecisionScopeSignal extends MemoryOverdueResolutionOutcomeScopeSignal {
  overdue_closure_decision: string;
  overdue_closure_priority: string;
  overdue_closure_target_memory_id: string | null;
  overdue_closure_reasons: string[];
}

export interface MemoryOverdueClosureDecisionsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_closure_decision_counts: Record<string, number>;
  highest_priority_overdue_closure_decision: string | null;
  highest_priority_overdue_closure_priority: string | null;
  highest_priority_overdue_closure_scope_kind: string | null;
  highest_priority_overdue_closure_scope_id: string | null;
  highest_priority_overdue_closure_target_memory_id: string | null;
  highest_priority_overdue_closure_reasons: string[];
  scopes: MemoryOverdueClosureDecisionScopeSignal[];
}

export interface MemoryOverdueArchiveRecommendationScopeSignal extends MemoryOverdueClosureDecisionScopeSignal {
  overdue_archive_recommendation: string;
  overdue_archive_priority: string;
  overdue_archive_target_memory_id: string | null;
  overdue_archive_reasons: string[];
}

export interface MemoryOverdueArchiveRecommendationsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_archive_recommendation_counts: Record<string, number>;
  highest_priority_overdue_archive_recommendation: string | null;
  highest_priority_overdue_archive_priority: string | null;
  highest_priority_overdue_archive_scope_kind: string | null;
  highest_priority_overdue_archive_scope_id: string | null;
  highest_priority_overdue_archive_target_memory_id: string | null;
  highest_priority_overdue_archive_reasons: string[];
  scopes: MemoryOverdueArchiveRecommendationScopeSignal[];
}

export interface MemoryOverdueRetentionGuidanceScopeSignal extends MemoryOverdueArchiveRecommendationScopeSignal {
  overdue_retention_guidance: string;
  overdue_retention_priority: string;
  overdue_retention_bucket: string;
  overdue_retention_target_memory_id: string | null;
  overdue_retention_reasons: string[];
}

export interface MemoryOverdueRetentionGuidanceResponse {
  session_id: string;
  status: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_retention_guidance_counts: Record<string, number>;
  highest_priority_overdue_retention_guidance: string | null;
  highest_priority_overdue_retention_priority: string | null;
  highest_priority_overdue_retention_scope_kind: string | null;
  highest_priority_overdue_retention_scope_id: string | null;
  highest_priority_overdue_retention_bucket: string | null;
  highest_priority_overdue_retention_target_memory_id: string | null;
  highest_priority_overdue_retention_reasons: string[];
  scopes: MemoryOverdueRetentionGuidanceScopeSignal[];
}

export interface MemoryOverdueRetentionWindowScopeSignal extends MemoryOverdueRetentionGuidanceScopeSignal {
  overdue_retention_window: string;
  overdue_retention_window_priority: string;
  overdue_retention_window_due_at: string | null;
  overdue_retention_window_target_memory_id: string | null;
  overdue_retention_window_reasons: string[];
}

export interface MemoryOverdueRetentionWindowsResponse {
  session_id: string;
  status: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
  overdue_retention_window_counts: Record<string, number>;
  highest_priority_overdue_retention_window: string | null;
  highest_priority_overdue_retention_window_priority: string | null;
  highest_priority_overdue_retention_window_scope_kind: string | null;
  highest_priority_overdue_retention_window_scope_id: string | null;
  highest_priority_overdue_retention_window_due_at: string | null;
  highest_priority_overdue_retention_window_target_memory_id: string | null;
  highest_priority_overdue_retention_window_reasons: string[];
  scopes: MemoryOverdueRetentionWindowScopeSignal[];
}
