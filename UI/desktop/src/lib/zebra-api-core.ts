import type {
  ApprovalDecisionResponse,
  ApprovalSummary,
  ApprovalsResponse,
  CreateSessionResponse,
  HealthResponse,
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
  SessionSummary,
} from "../types";
import { requestEventStream, requestJson } from "./zebra-api-helpers";

interface CoreApiContext {
  baseUrl: string;
  authToken: string;
}

export function buildCoreApiClient({ baseUrl, authToken }: CoreApiContext) {
  return {
    health: () => requestJson<HealthResponse>(baseUrl, "/health"),
    approvals: () => requestJson<ApprovalsResponse>(baseUrl, "/approvals", { authToken }),
    approval: (approvalId: string) =>
      requestJson<ApprovalSummary>(baseUrl, `/approvals/${approvalId}`, { authToken }),
    session: (sessionId: string) => requestJson<SessionSummary>(baseUrl, `/sessions/${sessionId}`, { authToken }),
    stream: (sessionId: string, onEvent?: (event: SessionEvent) => void) =>
      requestEventStream(baseUrl, `/sessions/${sessionId}/stream`, authToken, onEvent),
    diff: (sessionId: string) =>
      requestJson<SessionDiffResponse>(baseUrl, `/sessions/${sessionId}/diff`, { authToken }),
    artifacts: (sessionId: string) =>
      requestJson<SessionArtifactsResponse>(baseUrl, `/sessions/${sessionId}/artifacts`, { authToken }),
    artifactDetail: (sessionId: string, artifactId: string) =>
      requestJson<SessionArtifactDetailResponse>(baseUrl, `/sessions/${sessionId}/artifacts/${artifactId}`, {
        authToken,
      }),
    artifactContent: (sessionId: string, artifactId: string) =>
      requestJson<SessionArtifactContentResponse>(
        baseUrl,
        `/sessions/${sessionId}/artifacts/${artifactId}/content`,
        { authToken },
      ),
    pruneArtifact: (sessionId: string, artifactId: string) =>
      requestJson<SessionArtifactPruneResponse>(
        baseUrl,
        `/sessions/${sessionId}/artifacts/${artifactId}/prune`,
        {
          method: "POST",
          authToken,
          body: {},
        },
      ),
    deliveryAudit: (sessionId: string) =>
      requestJson<SessionDeliveryAuditResponse>(baseUrl, `/sessions/${sessionId}/delivery-audit`, { authToken }),
    createSession: (payload: { title: string; prompt: string; workspace?: string; execute?: boolean }) =>
      requestJson<CreateSessionResponse>(baseUrl, "/sessions", {
        method: "POST",
        authToken,
        body: payload,
      }),
    appendMessage: (sessionId: string, payload: { content: string }) =>
      requestJson<SessionMessageAppendResponse>(baseUrl, `/sessions/${sessionId}/messages`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    commit: (
      sessionId: string,
      payload: { message: string; author_name?: string; author_email?: string },
    ) =>
      requestJson<SessionCommitResponse>(baseUrl, `/sessions/${sessionId}/commit`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    pullRequest: (
      sessionId: string,
      payload: { title: string; body: string; base_branch: string; head_branch?: string; dry_run: boolean },
    ) =>
      requestJson<SessionPullRequestResponse>(baseUrl, `/sessions/${sessionId}/pull-request`, {
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
      requestJson<SessionControlResponse>(baseUrl, `/sessions/${sessionId}/suspend`, {
        method: "POST",
        authToken,
        body: {},
      }),
    cancel: (sessionId: string) =>
      requestJson<SessionControlResponse>(baseUrl, `/sessions/${sessionId}/cancel`, {
        method: "POST",
        authToken,
        body: {},
      }),
    resume: (sessionId: string, payload?: { worker_id?: string; lease_ttl_seconds?: number }) =>
      requestJson<SessionControlResponse>(baseUrl, `/sessions/${sessionId}/resume`, {
        method: "POST",
        authToken,
        body: payload ?? {},
      }),
  };
}
