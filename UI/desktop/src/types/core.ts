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

export interface McpToolCapability {
  name: string;
  description: string;
  input_fields: string[];
}

export interface McpServerCapability {
  name: string;
  tool_count: number;
  tools: McpToolCapability[];
}

export interface McpCapabilitiesResponse {
  status: "unconfigured" | "available" | "unavailable";
  configured: boolean;
  available: boolean;
  server_count: number;
  tool_count: number;
  servers: McpServerCapability[];
  reason?: string;
}

export interface ApprovalContext {
  tool_name?: string;
  reason?: string;
  policy_profile?: string;
  route?: string;
  target?: string;
  network_profile?: string;
  scope?: string[];
  arguments?: Record<string, unknown>;
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
