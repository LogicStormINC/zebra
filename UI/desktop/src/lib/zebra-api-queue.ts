import type {
  MemoryQueuePreviewResponse,
  MemoryQueueReviewResponse,
  SessionMemoryDecisionResponse,
} from "../types";
import { requestJson } from "./zebra-api-helpers";

type MemoryDecisionPayload = {
  decision: "confirm" | "expire";
  operator?: string;
  reason?: string;
};

export function buildQueueApiClient(baseUrl: string, authToken: string) {
  return {
    confirmMemory: (sessionId: string, memoryId: string, payload?: { operator?: string; reason?: string }) =>
      requestJson<SessionMemoryDecisionResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory/${memoryId}/confirm`,
        {
          method: "POST",
          authToken,
          body: payload ?? {},
        },
      ),
    expireMemory: (sessionId: string, memoryId: string, payload?: { operator?: string; reason?: string }) =>
      requestJson<SessionMemoryDecisionResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory/${memoryId}/expire`,
        {
          method: "POST",
          authToken,
          body: payload ?? {},
        },
      ),
    previewSessionMemoryQueue: (
      sessionId: string,
      payload: Omit<MemoryDecisionPayload, "operator" | "reason"> & { memory_type?: string },
    ) =>
      requestJson<MemoryQueuePreviewResponse>(baseUrl, `/sessions/${sessionId}/memory/review-queue-preview`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    reviewSessionMemoryQueue: (sessionId: string, payload: MemoryDecisionPayload) =>
      requestJson<MemoryQueueReviewResponse>(baseUrl, `/sessions/${sessionId}/memory/review-queue`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    bulkReviewSessionMemory: (
      sessionId: string,
      payload: MemoryDecisionPayload & { memory_ids: string[] },
    ) =>
      requestJson<MemoryQueueReviewResponse>(baseUrl, `/sessions/${sessionId}/memory/bulk-review`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    previewUserMemoryQueue: (userId: string, payload: Omit<MemoryDecisionPayload, "operator" | "reason"> & { memory_type?: string }) =>
      requestJson<MemoryQueuePreviewResponse>(baseUrl, `/users/${userId}/memory/review-queue-preview`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    reviewUserMemoryQueue: (userId: string, payload: MemoryDecisionPayload) =>
      requestJson<MemoryQueueReviewResponse>(baseUrl, `/users/${userId}/memory/review-queue`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    bulkReviewUserMemory: (
      userId: string,
      payload: MemoryDecisionPayload & { memory_ids: string[] },
    ) =>
      requestJson<MemoryQueueReviewResponse>(baseUrl, `/users/${userId}/memory/bulk-review`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    previewTenantMemoryQueue: (
      tenantId: string,
      payload: Omit<MemoryDecisionPayload, "operator" | "reason"> & { memory_type?: string },
    ) =>
      requestJson<MemoryQueuePreviewResponse>(baseUrl, `/tenants/${tenantId}/memory/review-queue-preview`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    reviewTenantMemoryQueue: (tenantId: string, payload: MemoryDecisionPayload) =>
      requestJson<MemoryQueueReviewResponse>(baseUrl, `/tenants/${tenantId}/memory/review-queue`, {
        method: "POST",
        authToken,
        body: payload,
      }),
    bulkReviewTenantMemory: (
      tenantId: string,
      payload: MemoryDecisionPayload & { memory_ids: string[] },
    ) =>
      requestJson<MemoryQueueReviewResponse>(baseUrl, `/tenants/${tenantId}/memory/bulk-review`, {
        method: "POST",
        authToken,
        body: payload,
      }),
  };
}
