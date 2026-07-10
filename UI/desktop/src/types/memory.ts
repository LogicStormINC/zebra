import type { QueryScopeKind } from "./core";
export interface MemoryReview {
  recorded_at: string;
  previous_status: string;
  status: string;
  operator: string;
  reason?: string | null;
  superseded_memory_ids: string[];
  duplicate_of_memory_id?: string | null;
}

export interface MemorySource {
  kind: string;
  event_type: string;
  tool_name?: string;
  source_event_start: number;
  source_event_end: number;
  captured_at: string;
  locator?: string;
  cwd?: string;
  preset?: string;
}

export interface MemoryRecord {
  memory_id: string;
  memory_type: string;
  text: string;
  confidence: number;
  status: string;
  visibility: string;
  created_at: string;
  updated_at: string;
  source_session_id?: string | null;
  source_event_start?: number | null;
  source_event_end?: number | null;
  source?: MemorySource;
  last_review?: MemoryReview;
}

export interface SessionMemoryResponse {
  session_id: string;
  repo_id: string;
  memories: MemoryRecord[];
}

export interface ScopeQueueSummary {
  scope_kind: QueryScopeKind;
  scope_id: string;
  pending_count: number;
  queue_status: string;
  latest_memory_id?: string | null;
  latest_updated_at?: string | null;
}
export interface MemoryOverviewResponse {
  session_id: string;
  status: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  scope_count: number;
  total_pending_count: number;
  scopes: ScopeQueueSummary[];
}

export interface SessionMemoryDecisionResponse {
  session_id: string;
  memory_id: string;
  decision: string;
  event_type: string;
  sequence: number;
  status: string;
  memory_status: string;
  superseded_memory_ids: string[];
  duplicate_of_memory_id: string | null;
}
export type MemoryScopeKind = "session" | "user" | "tenant";

export interface MemoryQueueTargetExplanation {
  memory_id: string;
  memory_type: string;
  current_status: string;
  target_scope_kind: MemoryScopeKind;
  target_scope_id: string;
  target_reason: string;
}

export interface MemoryQueueProjectedResult {
  memory_id: string;
  memory_type: string;
  current_status: string;
  projected_status: string;
}

export interface MemoryQueuePreviewResponse {
  status: string;
  decision: string;
  queue_sweep_preview: boolean;
  memory_type_filter: string | null;
  filtered_from_queued_count: number;
  queued_count: number;
  target_scope_kind: MemoryScopeKind;
  target_scope_id: string;
  target_reason_counts: Record<string, number>;
  target_explanations: MemoryQueueTargetExplanation[];
  projected_applied_count: number;
  projected_memory_status: string;
  projected_by_type: Record<string, number>;
  projected_results: MemoryQueueProjectedResult[];
  memory_ids: string[];
  memories: MemoryRecord[];
  session_id?: string;
  user_id?: string;
  tenant_id?: string;
}

export interface MemoryBulkOutcome {
  outcome: "applied" | "skipped" | "invalid";
  memory_id: string;
  status?: string;
  reason?: string;
  session_id?: string;
  user_id?: string;
  tenant_id?: string;
  decision?: string;
  event_type?: string;
  sequence?: number;
  memory_status?: string;
  superseded_memory_ids?: string[];
  duplicate_of_memory_id?: string | null;
}

export interface MemoryQueueReviewResponse {
  status: string;
  queue_sweep?: boolean;
  queued_count?: number;
  decision: string;
  total_requested: number;
  applied_count: number;
  skipped_count: number;
  invalid_count: number;
  results: MemoryBulkOutcome[];
  session_id?: string;
  user_id?: string;
  tenant_id?: string;
}

export interface ScopeMemoryInventoryResponse {
  session_id?: string;
  user_id?: string;
  tenant_id?: string;
  repo_id?: string;
  memories: MemoryRecord[];
}

export interface ScopeMemoryQueueSummaryResponse {
  session_id?: string;
  user_id?: string;
  tenant_id?: string;
  repo_id?: string;
  pending_count: number;
  queue_status: string;
  latest_memory_id: string | null;
  latest_updated_at: string | null;
}

export interface MemoryGovernanceScopeSignal {
  scope_kind: "repo" | "user" | "tenant";
  scope_id: string;
  pending_count: number;
  queue_status: string;
  latest_memory_id: string | null;
  latest_updated_at: string | null;
  pending_by_type: Record<string, number>;
  reviewed_count: number;
  review_status_counts: Record<string, number>;
  latest_reviewed_at: string | null;
  latest_review_status: string | null;
  latest_review_operator: string | null;
}

export interface MemoryGovernanceSignalsResponse {
  session_id: string;
  status: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  scope_count: number;
  total_pending_count: number;
  total_reviewed_count: number;
  review_status_totals: Record<string, number>;
  scopes: MemoryGovernanceScopeSignal[];
}

export interface MemoryPressureScopeSignal extends MemoryGovernanceScopeSignal {
  reference_at: string;
  pending_age_buckets: Record<string, number>;
  oldest_pending_memory_id: string | null;
  oldest_pending_captured_at: string | null;
  oldest_pending_age_seconds: number | null;
  reviewed_last_24h_count: number;
  reviewed_last_7d_count: number;
  reviewed_last_30d_count: number;
  latest_review_window: string | null;
  pressure_level: string;
  pressure_reasons: string[];
}

export interface MemoryPressureSignalsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  total_pending_count: number;
  pending_age_bucket_totals: Record<string, number>;
  total_reviewed_last_24h_count: number;
  total_reviewed_last_7d_count: number;
  pressure_level_counts: Record<string, number>;
  highest_pressure_level: string | null;
  highest_pressure_scope_kind: string | null;
  highest_pressure_scope_id: string | null;
  highest_pressure_reasons: string[];
  scopes: MemoryPressureScopeSignal[];
}

export interface MemoryActionHintScopeSignal extends MemoryPressureScopeSignal {
  action_hint: string;
  action_priority: string;
  action_target_memory_id: string | null;
  action_reasons: string[];
}

export interface MemoryActionHintsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  action_hint_counts: Record<string, number>;
  highest_priority_action_hint: string | null;
  highest_priority_action_priority: string | null;
  highest_priority_action_scope_kind: string | null;
  highest_priority_action_scope_id: string | null;
  highest_priority_action_target_memory_id: string | null;
  highest_priority_action_reasons: string[];
  scopes: MemoryActionHintScopeSignal[];
}

export interface MemoryEscalationScopeSignal extends MemoryActionHintScopeSignal {
  escalation_recommendation: string;
  escalation_priority: string;
  escalation_target_memory_id: string | null;
  escalation_reasons: string[];
}

export interface MemoryEscalationsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  escalation_recommendation_counts: Record<string, number>;
  highest_priority_escalation_recommendation: string | null;
  highest_priority_escalation_priority: string | null;
  highest_priority_escalation_scope_kind: string | null;
  highest_priority_escalation_scope_id: string | null;
  highest_priority_escalation_target_memory_id: string | null;
  highest_priority_escalation_reasons: string[];
  scopes: MemoryEscalationScopeSignal[];
}

export interface MemoryFollowUpScopeSignal extends MemoryEscalationScopeSignal {
  follow_up_window: string;
  follow_up_priority: string;
  follow_up_due_at: string | null;
  follow_up_target_memory_id: string | null;
  follow_up_reasons: string[];
}

export interface MemoryFollowUpWindowsResponse {
  session_id: string;
  repo_id: string;
  user_id: string | null;
  tenant_id: string | null;
  reference_at: string;
  scope_count: number;
  follow_up_window_counts: Record<string, number>;
  highest_priority_follow_up_window: string | null;
  highest_priority_follow_up_priority: string | null;
  highest_priority_follow_up_scope_kind: string | null;
  highest_priority_follow_up_scope_id: string | null;
  highest_priority_follow_up_due_at: string | null;
  highest_priority_follow_up_target_memory_id: string | null;
  highest_priority_follow_up_reasons: string[];
  scopes: MemoryFollowUpScopeSignal[];
}
