import type { ApprovalContext } from "./core";

export interface SessionWorkspaceSnapshot {
  runtime_name: string;
  snapshot_id: string;
  snapshot_path: string;
}

export interface SessionWorkspace {
  workspace_root: string;
  status: string;
  current_sequence: number;
  prepared_at: string;
  updated_at: string;
  policy_profile: string;
  tool_profile: "general" | "coding";
  last_attempt_number: number;
  snapshot?: SessionWorkspaceSnapshot;
}

export interface SessionSummary {
  session_id: string;
  title: string;
  status: string;
  current_sequence: number;
  workspace?: SessionWorkspace;
  approval_context?: ApprovalContext;
}

export interface RecentSessionSummary extends SessionSummary {
  created_at: string;
  updated_at: string;
}

export interface SessionListResponse {
  sessions: RecentSessionSummary[];
  count: number;
  limit: number;
}

export interface SessionEvent {
  event_id: string;
  sequence: number;
  event_type: string;
  actor: string;
  created_at: string;
  payload: Record<string, unknown>;
}

export interface SessionStreamResponse {
  session_id: string;
  events: SessionEvent[];
}

export interface SessionDiffResponse {
  session_id: string;
  workspace: string;
  clean: boolean;
  git_status: string;
  diff: string;
}

export interface CreateSessionResponse {
  session_id: string;
  title: string;
  status: string;
  executed: boolean;
  assistant_message?: string;
  tool_profile?: "general" | "coding";
}

export interface ApprovalDecisionResponse {
  approval_id: string;
  session_id: string;
  decision: string;
  event_type: string;
  sequence: number;
  status: string;
  approval_context?: ApprovalContext;
}

export interface SessionControlResponse {
  session_id: string;
  suspended?: boolean;
  cancelled?: boolean;
  executed?: boolean;
  worker_id?: string;
  status: string;
  workspace_status?: string;
  snapshot_id?: string | null;
  current_sequence?: number;
  assistant_message?: string | null;
  trace?: Array<{
    attempt_number: number;
    assistant_message: string | null;
    tools: Array<Record<string, unknown>>;
  }>;
}

export interface SessionMessageAppendResponse {
  session_id: string;
  appended: boolean;
  content: string;
  sequence: number;
  status: string;
  current_sequence: number;
}

export interface SessionCommitResponse {
  session_id: string;
  committed?: boolean;
  message?: string;
  workspace?: string;
  policy_profile?: string;
  idempotency_key?: string | null;
  commit_sha?: string;
  status?: string;
  reason?: string;
}

export interface PullRequestPlan {
  provider: string;
  title: string;
  body: string;
  base_branch: string;
  head_branch?: string | null;
  commit_sha: string;
  dry_run: boolean;
  status: string;
  url?: string | null;
  credential_source?: string | null;
  credential_backend?: string | null;
  request_payload?: Record<string, unknown>;
}

export interface SessionPullRequestResponse {
  session_id: string;
  policy_profile?: string;
  idempotency_key?: string | null;
  pull_request?: PullRequestPlan;
  status?: string;
  reason?: string;
}
