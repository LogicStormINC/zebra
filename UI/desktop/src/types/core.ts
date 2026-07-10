export type QueryScopeKind = "repo" | "user" | "tenant";

export interface OperatorConfig {
  apiBaseUrl: string;
  authToken: string;
  sessionId: string;
  userId: string;
  tenantId: string;
}

export interface ApiErrorPayload {
  status?: string;
  reason?: string;
  [key: string]: unknown;
}

export interface HealthResponse {
  status: string;
  service: string;
}

export interface ApprovalContext {
  tool_name?: string;
  reason?: string;
  policy_profile?: string;
  route?: string;
  target?: string;
  network_profile?: string;
  scope?: string[];
}

export interface ApprovalSummary {
  approval_id: string;
  session_id: string;
  title: string;
  status: string;
  current_sequence: number;
  approval_context?: ApprovalContext;
}

export interface ApprovalsResponse {
  approvals: ApprovalSummary[];
}
