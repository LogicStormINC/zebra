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
  runtime: {
    profile: string;
    runtime_class: string;
    fallback_allowed: boolean;
  };
}

export interface McpToolCapability {
  name: string;
  description: string;
  input_fields: string[];
}

export interface McpResourceCapability {
  resource_id: string;
  name: string;
  description: string;
  mime_type: string | null;
  size_bytes: number | null;
}

export interface McpServerCapability {
  name: string;
  tool_count: number;
  tools: McpToolCapability[];
  resource_count?: number;
  resources?: McpResourceCapability[];
}

export interface McpCapabilitiesResponse {
  status: "unconfigured" | "available" | "unavailable";
  configured: boolean;
  available: boolean;
  server_count: number;
  tool_count: number;
  resource_count?: number;
  servers: McpServerCapability[];
  reason?: string;
}

export interface McpPromptArgumentCapability {
  name: string;
  description: string;
  required: boolean;
}

export interface McpPromptCapability {
  prompt_id: string;
  name: string;
  description: string;
  arguments: McpPromptArgumentCapability[];
  available: boolean;
}

export interface McpPromptsResponse {
  status: "unconfigured" | "available" | "unavailable";
  configured: boolean;
  available: boolean;
  prompt_count: number;
  prompts: McpPromptCapability[];
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
