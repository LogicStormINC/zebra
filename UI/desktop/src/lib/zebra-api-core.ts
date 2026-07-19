import type {
  ApprovalDecisionResponse,
  ApprovalSummary,
  ApprovalsResponse,
  CreateSessionResponse,
  HealthResponse,
  McpCapabilitiesResponse,
  McpPromptsResponse,
  SessionArtifactContentResponse,
  SessionArtifactDetailResponse,
  SessionArtifactPruneResponse,
  SessionArtifactsResponse,
  SessionControlResponse,
  SessionCommitResponse,
  SessionDeliveryAuditResponse,
  SessionDiffResponse,
  SessionEvent,
  SessionMessageAppendResponse,
  SessionPullRequestResponse,
  SessionListResponse,
  SessionSummary,
} from "../types";
import { requestEventStream, requestJson } from "./zebra-api-helpers";
import type { AttachmentPayload } from "./text-attachments";

interface CoreApiContext {
  baseUrl: string;
  authToken: string;
}

export function buildCoreApiClient({ baseUrl, authToken }: CoreApiContext) {
  return {
    health: () => requestJson<HealthResponse>(baseUrl, "/health"),
    mcpCapabilities: () =>
      requestJson<McpCapabilitiesResponse>(baseUrl, "/capabilities/mcp", { authToken }),
    mcpPrompts: () =>
      requestJson<McpPromptsResponse>(baseUrl, "/capabilities/mcp/prompts", { authToken }),
    approvals: () => requestJson<ApprovalsResponse>(baseUrl, "/approvals", { authToken }),
    approval: (approvalId: string) =>
      requestJson<ApprovalSummary>(baseUrl, `/approvals/${approvalId}`, { authToken }),
    session: (taskId: string) => requestJson<SessionSummary>(baseUrl, `/tasks/${taskId}`, { authToken }),
    sessions: (limit = 100) => requestJson<SessionListResponse>(baseUrl, `/tasks?limit=${limit}`, { authToken }),
    stream: (
      sessionId: string,
      onEvent?: (event: SessionEvent) => void,
      options?: { signal?: AbortSignal; afterSequence?: number },
    ) => requestEventStream(
      baseUrl,
      `/tasks/${sessionId}/stream`,
      authToken,
      onEvent,
      options,
    ),
    diff: (sessionId: string) =>
      requestJson<SessionDiffResponse>(baseUrl, `/tasks/${sessionId}/diff`, { authToken }),
    artifacts: (sessionId: string) =>
      requestJson<SessionArtifactsResponse>(baseUrl, `/tasks/${sessionId}/artifacts`, { authToken }),
    artifactDetail: (sessionId: string, artifactId: string) =>
      requestJson<SessionArtifactDetailResponse>(baseUrl, `/tasks/${sessionId}/artifacts/${artifactId}`, {
        authToken,
      }),
    artifactContent: (sessionId: string, artifactId: string) =>
      requestJson<SessionArtifactContentResponse>(
        baseUrl,
        `/tasks/${sessionId}/artifacts/${artifactId}/content`,
        { authToken },
      ),
    pruneArtifact: (sessionId: string, artifactId: string) =>
      requestJson<SessionArtifactPruneResponse>(
        baseUrl,
        `/tasks/${sessionId}/artifacts/${artifactId}/prune`,
        {
          method: "POST",
          authToken,
          body: {},
        },
      ),
    deliveryAudit: (sessionId: string) =>
      requestJson<SessionDeliveryAuditResponse>(baseUrl, `/tasks/${sessionId}/delivery-audit`, { authToken }),
    createSession: (payload: { title: string; prompt: string; workspace?: string; execute?: boolean; policy_profile?: string; tool_profile?: string; network_profile?: string; network_allowlist?: string[]; mcp_allowlist?: string[]; mcp_resource_ids?: string[]; mcp_prompt_id?: string; mcp_prompt_arguments?: Record<string, string>; attachments?: AttachmentPayload[] }) =>
      requestJson<CreateSessionResponse>(baseUrl, "/tasks", {
        method: "POST",
        authToken,
        body: payload,
      }),
    appendMessage: (sessionId: string, payload: { content: string; clarification_id?: string; attachments?: AttachmentPayload[] }) =>
      requestJson<SessionMessageAppendResponse>(baseUrl, `/tasks/${sessionId}/messages`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    commit: (
      sessionId: string,
      payload: { message: string; author_name?: string; author_email?: string },
    ) =>
      requestJson<SessionCommitResponse>(baseUrl, `/tasks/${sessionId}/commit`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    pullRequest: (
      sessionId: string,
      payload: { title: string; body: string; base_branch: string; head_branch?: string; dry_run: boolean },
    ) =>
      requestJson<SessionPullRequestResponse>(baseUrl, `/tasks/${sessionId}/pull-request`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    approve: (approvalId: string, payload?: { operator?: string; reason?: string }) =>
      requestJson<ApprovalDecisionResponse>(baseUrl, `/approvals/${approvalId}/approve`, {
        method: "POST",
        authToken,
        body: payload ?? {},
      }),
    reject: (approvalId: string, payload?: { operator?: string; reason?: string }) =>
      requestJson<ApprovalDecisionResponse>(baseUrl, `/approvals/${approvalId}/reject`, {
        method: "POST",
        authToken,
        body: payload ?? {},
      }),
    suspend: (sessionId: string) =>
      requestJson<SessionControlResponse>(baseUrl, `/tasks/${sessionId}/suspend`, {
        method: "POST",
        authToken,
        body: {},
      }),
    cancel: (sessionId: string) =>
      requestJson<SessionControlResponse>(baseUrl, `/tasks/${sessionId}/cancel`, {
        method: "POST",
        authToken,
        body: {},
      }),
    resume: (sessionId: string, payload?: { worker_id?: string; lease_ttl_seconds?: number }) =>
      requestJson<SessionControlResponse>(baseUrl, `/tasks/${sessionId}/resume`, {
        method: "POST",
        authToken,
        body: payload ?? {},
      }),
  };
}
