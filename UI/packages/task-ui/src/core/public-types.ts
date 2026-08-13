/**
 * Generic public Task UI types shared by every consumer.
 *
 * Security contract: these types carry only public-safe fields. Raw tool
 * arguments, full tool output, policy reasons, grants, prompts, reasoning,
 * internal segment ids, paths, and credentials must never appear here.
 */

export interface SessionEvent {
  event_id: string;
  sequence: number;
  event_type: string;
  /** Present on the raw runtime stream; sanitized envelopes may omit it. */
  actor?: string;
  created_at: string;
  payload: Record<string, unknown>;
}

export interface ChatMessage {
  key: string;
  role: "assistant" | "user";
  status?: "success" | "error";
  content: string;
}

export type PlanStepStatus = "pending" | "in_progress" | "completed" | "cancelled";

export interface TaskPlanStep {
  step_id: string;
  content: string;
  status: PlanStepStatus;
}

export interface TaskPlan {
  steps: TaskPlanStep[];
  summary: Record<PlanStepStatus | "total", number>;
  updated_at?: string;
}

export interface ClarificationContext {
  clarification_id: string;
  question: string;
  choices: string[];
  context?: string;
  requested_at: string;
}

/** Public-safe approval context; raw arguments are intentionally absent. */
export interface TaskApprovalContext {
  tool_name?: string;
  reason?: string;
  policy_profile?: string;
  route?: string;
  target?: string;
  network_profile?: string;
  scope?: string[];
}

export type TaskApprovalState = "pending" | "approved" | "rejected";

export interface TaskApproval {
  approval_context?: TaskApprovalContext;
  state: TaskApprovalState;
}
