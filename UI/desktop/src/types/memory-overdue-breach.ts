import type { MemoryFollowUpScopeSignal } from "./memory";

export interface MemoryOverdueRetentionBreachScopeSignal extends MemoryFollowUpScopeSignal {
  follow_up_overdue: boolean;
  overdue_retention_breach: string;
  overdue_retention_breach_priority: string;
  due_at: string | null;
  overdue_retention_breach_target_memory_id: string | null;
  overdue_retention_breach_reasons: string[];
}

export interface MemoryOverdueRetentionBreachAgingScopeSignal extends MemoryOverdueRetentionBreachScopeSignal {
  overdue_retention_breach_age_bucket: string;
  overdue_retention_breach_age_seconds: number;
  overdue_retention_breach_age_days: number;
  overdue_retention_breach_age_reasons: string[];
}

export interface MemoryOverdueRetentionBreachActionScopeSignal extends MemoryOverdueRetentionBreachAgingScopeSignal {
  overdue_retention_breach_action: string;
  overdue_retention_breach_action_priority: string;
  overdue_retention_breach_action_target_memory_id: string | null;
  overdue_retention_breach_action_reasons: string[];
}

export interface MemoryOverdueRetentionBreachLaneScopeSignal extends MemoryOverdueRetentionBreachActionScopeSignal {
  overdue_retention_breach_lane: string;
  overdue_retention_breach_lane_priority: string;
  overdue_retention_breach_lane_target_memory_id: string | null;
  overdue_retention_breach_lane_reasons: string[];
}

export interface MemoryOverdueRetentionBreachOwnerTargetScopeSignal extends MemoryOverdueRetentionBreachLaneScopeSignal {
  overdue_retention_breach_owner_target: string;
  overdue_retention_breach_owner_target_priority: string;
  overdue_retention_breach_owner_target_memory_id: string | null;
  overdue_retention_breach_owner_target_reasons: string[];
}

export interface MemoryOverdueRetentionBreachFollowThroughModeScopeSignal
  extends MemoryOverdueRetentionBreachOwnerTargetScopeSignal {
  overdue_retention_breach_follow_through_mode: string;
  overdue_retention_breach_follow_through_priority: string;
  overdue_retention_breach_follow_through_memory_id: string | null;
  overdue_retention_breach_follow_through_reasons: string[];
}

export interface MemoryOverdueRetentionBreachFollowThroughOutcomeScopeSignal
  extends MemoryOverdueRetentionBreachFollowThroughModeScopeSignal {
  overdue_retention_breach_follow_through_outcome: string;
  overdue_retention_breach_follow_through_outcome_priority: string;
  overdue_retention_breach_follow_through_outcome_memory_id: string | null;
  overdue_retention_breach_follow_through_outcome_reasons: string[];
}

export interface MemoryOverdueRetentionBreachFollowThroughCompletionScopeSignal
  extends MemoryOverdueRetentionBreachFollowThroughOutcomeScopeSignal {
  overdue_retention_breach_follow_through_completion_state: string;
  overdue_retention_breach_follow_through_completion_priority: string;
  overdue_retention_breach_follow_through_completion_memory_id: string | null;
  overdue_retention_breach_follow_through_completion_reasons: string[];
}

export interface MemoryOverdueRetentionBreachFollowThroughVerificationStateScopeSignal
  extends MemoryOverdueRetentionBreachFollowThroughCompletionScopeSignal {
  overdue_retention_breach_follow_through_verification_state: string;
  overdue_retention_breach_follow_through_verification_priority: string;
  overdue_retention_breach_follow_through_verification_memory_id: string | null;
  overdue_retention_breach_follow_through_verification_reasons: string[];
}

export interface MemoryOverdueRetentionBreachFollowThroughVerificationOutcomeScopeSignal
  extends MemoryOverdueRetentionBreachFollowThroughVerificationStateScopeSignal {
  overdue_retention_breach_follow_through_verification_outcome: string;
  overdue_retention_breach_follow_through_verification_outcome_priority: string;
  overdue_retention_breach_follow_through_verification_outcome_memory_id: string | null;
  overdue_retention_breach_follow_through_verification_outcome_reasons: string[];
}

interface MemoryOverdueRetentionBreachResponseBase {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  overdue_scope_count: number;
}

export interface MemoryOverdueBreachesResponse extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_counts: Record<string, number>;
  highest_priority_overdue_retention_breach: string | null;
  highest_priority_overdue_retention_breach_priority: string | null;
  highest_priority_overdue_retention_breach_scope_kind: string | null;
  highest_priority_overdue_retention_breach_scope_id: string | null;
  highest_priority_overdue_retention_breach_due_at: string | null;
  highest_priority_overdue_retention_breach_target_memory_id: string | null;
  highest_priority_overdue_retention_breach_reasons: string[];
  scopes: MemoryOverdueRetentionBreachScopeSignal[];
}

export interface MemoryOverdueRetentionBreachAgingResponse extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_age_bucket_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_age_bucket: string | null;
  highest_priority_overdue_retention_breach_age_scope_kind: string | null;
  highest_priority_overdue_retention_breach_age_scope_id: string | null;
  highest_priority_overdue_retention_breach_age_seconds: number | null;
  highest_priority_overdue_retention_breach_age_days: number | null;
  highest_priority_overdue_retention_breach_age_reasons: string[];
  scopes: MemoryOverdueRetentionBreachAgingScopeSignal[];
}

export interface MemoryOverdueRetentionBreachActionsResponse extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_action_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_action: string | null;
  highest_priority_overdue_retention_breach_action_priority: string | null;
  highest_priority_overdue_retention_breach_action_scope_kind: string | null;
  highest_priority_overdue_retention_breach_action_scope_id: string | null;
  highest_priority_overdue_retention_breach_action_target_memory_id: string | null;
  highest_priority_overdue_retention_breach_action_reasons: string[];
  scopes: MemoryOverdueRetentionBreachActionScopeSignal[];
}

export interface MemoryOverdueRetentionBreachLanesResponse extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_lane_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_lane: string | null;
  highest_priority_overdue_retention_breach_lane_priority: string | null;
  highest_priority_overdue_retention_breach_lane_scope_kind: string | null;
  highest_priority_overdue_retention_breach_lane_scope_id: string | null;
  highest_priority_overdue_retention_breach_lane_target_memory_id: string | null;
  highest_priority_overdue_retention_breach_lane_reasons: string[];
  scopes: MemoryOverdueRetentionBreachLaneScopeSignal[];
}

export interface MemoryOverdueRetentionBreachOwnerTargetsResponse extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_owner_target_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_owner_target: string | null;
  highest_priority_overdue_retention_breach_owner_target_priority: string | null;
  highest_priority_overdue_retention_breach_owner_target_scope_kind: string | null;
  highest_priority_overdue_retention_breach_owner_target_scope_id: string | null;
  highest_priority_overdue_retention_breach_owner_target_memory_id: string | null;
  highest_priority_overdue_retention_breach_owner_target_reasons: string[];
  scopes: MemoryOverdueRetentionBreachOwnerTargetScopeSignal[];
}

export interface MemoryOverdueRetentionBreachFollowThroughModesResponse extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_follow_through_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_follow_through_mode: string | null;
  highest_priority_overdue_retention_breach_follow_through_priority: string | null;
  highest_priority_overdue_retention_breach_follow_through_scope_kind: string | null;
  highest_priority_overdue_retention_breach_follow_through_scope_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_memory_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_reasons: string[];
  scopes: MemoryOverdueRetentionBreachFollowThroughModeScopeSignal[];
}

export interface MemoryOverdueRetentionBreachFollowThroughOutcomesResponse
  extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_follow_through_outcome_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_follow_through_outcome: string | null;
  highest_priority_overdue_retention_breach_follow_through_outcome_priority: string | null;
  highest_priority_overdue_retention_breach_follow_through_outcome_scope_kind: string | null;
  highest_priority_overdue_retention_breach_follow_through_outcome_scope_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_outcome_memory_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_outcome_reasons: string[];
  scopes: MemoryOverdueRetentionBreachFollowThroughOutcomeScopeSignal[];
}

export interface MemoryOverdueRetentionBreachFollowThroughCompletionStatesResponse
  extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_follow_through_completion_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_follow_through_completion_state: string | null;
  highest_priority_overdue_retention_breach_follow_through_completion_priority: string | null;
  highest_priority_overdue_retention_breach_follow_through_completion_scope_kind: string | null;
  highest_priority_overdue_retention_breach_follow_through_completion_scope_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_completion_memory_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_completion_reasons: string[];
  scopes: MemoryOverdueRetentionBreachFollowThroughCompletionScopeSignal[];
}

export interface MemoryOverdueRetentionBreachFollowThroughVerificationStatesResponse
  extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_follow_through_verification_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_follow_through_verification_state: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_priority: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_scope_kind: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_scope_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_memory_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_reasons: string[];
  scopes: MemoryOverdueRetentionBreachFollowThroughVerificationStateScopeSignal[];
}

export interface MemoryOverdueRetentionBreachFollowThroughVerificationOutcomesResponse
  extends MemoryOverdueRetentionBreachResponseBase {
  overdue_retention_breach_follow_through_verification_outcome_counts: Record<string, number>;
  highest_priority_overdue_retention_breach_follow_through_verification_outcome: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_outcome_priority: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope_kind: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_outcome_memory_id: string | null;
  highest_priority_overdue_retention_breach_follow_through_verification_outcome_reasons: string[];
  scopes: MemoryOverdueRetentionBreachFollowThroughVerificationOutcomeScopeSignal[];
}

