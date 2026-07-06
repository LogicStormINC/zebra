import type {
  SessionMemoryResponse,
  MemoryActionHintsResponse,
  MemoryEscalationsResponse,
  MemoryFollowUpWindowsResponse,
  MemoryGovernanceSignalsResponse,
  MemoryOverviewResponse,
  MemoryOverdueAgeBucketsResponse,
  MemoryOverdueArchiveRecommendationsResponse,
  MemoryOverdueClosureDecisionsResponse,
  MemoryOverdueEscalationLanesResponse,
  MemoryOverdueFlagsResponse,
  MemoryOverdueInterventionsResponse,
  MemoryOverdueRecoveryPathsResponse,
  MemoryOverdueRetentionBreachActionsResponse,
  MemoryOverdueRetentionBreachAgingResponse,
  MemoryOverdueRetentionBreachFollowThroughCompletionStatesResponse,
  MemoryOverdueRetentionBreachFollowThroughModesResponse,
  MemoryOverdueRetentionBreachFollowThroughOutcomesResponse,
  MemoryOverdueRetentionBreachFollowThroughVerificationOutcomesResponse,
  MemoryOverdueRetentionBreachFollowThroughVerificationStatesResponse,
  MemoryOverdueRetentionBreachLanesResponse,
  MemoryOverdueRetentionBreachOwnerTargetsResponse,
  MemoryOverdueBreachesResponse,
  MemoryOverdueRetentionGuidanceResponse,
  MemoryOverdueRetentionWindowsResponse,
  MemoryOverdueResolutionCheckpointsResponse,
  MemoryOverdueResolutionOutcomesResponse,
  MemoryOverdueTrendSignalsResponse,
  MemoryOverdueTypeRollupsResponse,
  MemoryOverdueVisibilityRollupsResponse,
  MemoryPressureSignalsResponse,
  ScopeMemoryInventoryResponse,
  ScopeMemoryQueueSummaryResponse,
} from "../types";
import { requestJson } from "./zebra-api-helpers";

const withScopeBody = (userId: string, tenantId: string) => ({
  user_id: userId.trim() || undefined,
  tenant_id: tenantId.trim() || undefined,
});

export function buildMemoryApi(baseUrl: string, authToken: string, userId: string, tenantId: string) {
  return {
    memory: (sessionId: string) =>
      requestJson<SessionMemoryResponse>(baseUrl, `/sessions/${sessionId}/memory`, { authToken }),
    sessionMemoryQueueSummary: (sessionId: string) =>
      requestJson<ScopeMemoryQueueSummaryResponse>(baseUrl, `/sessions/${sessionId}/memory/queue-summary`, {
        authToken,
      }),
    userMemory: (userId: string) =>
      requestJson<ScopeMemoryInventoryResponse>(baseUrl, `/users/${userId}/memory`, { authToken }),
    userMemoryQueueSummary: (userId: string) =>
      requestJson<ScopeMemoryQueueSummaryResponse>(baseUrl, `/users/${userId}/memory/queue-summary`, {
        authToken,
      }),
    tenantMemory: (tenantId: string) =>
      requestJson<ScopeMemoryInventoryResponse>(baseUrl, `/tenants/${tenantId}/memory`, { authToken }),
    tenantMemoryQueueSummary: (tenantId: string) =>
      requestJson<ScopeMemoryQueueSummaryResponse>(baseUrl, `/tenants/${tenantId}/memory/queue-summary`, {
        authToken,
      }),
    memoryOverview: (sessionId: string) =>
      requestJson<MemoryOverviewResponse>(baseUrl, `/sessions/${sessionId}/memory-overview`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryGovernance: (sessionId: string) =>
      requestJson<MemoryGovernanceSignalsResponse>(baseUrl, `/sessions/${sessionId}/memory-governance`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryActionHints: (sessionId: string) =>
      requestJson<MemoryActionHintsResponse>(baseUrl, `/sessions/${sessionId}/memory-action-hints`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryPressure: (sessionId: string) =>
      requestJson<MemoryPressureSignalsResponse>(baseUrl, `/sessions/${sessionId}/memory-pressure`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryEscalations: (sessionId: string) =>
      requestJson<MemoryEscalationsResponse>(baseUrl, `/sessions/${sessionId}/memory-escalations`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryFollowUpWindows: (sessionId: string) =>
      requestJson<MemoryFollowUpWindowsResponse>(baseUrl, `/sessions/${sessionId}/memory-follow-up-windows`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryOverdueFlags: (sessionId: string) =>
      requestJson<MemoryOverdueFlagsResponse>(baseUrl, `/sessions/${sessionId}/memory-overdue-flags`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryOverdueAgeBuckets: (sessionId: string) =>
      requestJson<MemoryOverdueAgeBucketsResponse>(baseUrl, `/sessions/${sessionId}/memory-overdue-age-buckets`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryOverdueTypes: (sessionId: string) =>
      requestJson<MemoryOverdueTypeRollupsResponse>(baseUrl, `/sessions/${sessionId}/memory-overdue-types`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryOverdueVisibility: (sessionId: string) =>
      requestJson<MemoryOverdueVisibilityRollupsResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-visibility`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueTrends: (sessionId: string) =>
      requestJson<MemoryOverdueTrendSignalsResponse>(baseUrl, `/sessions/${sessionId}/memory-overdue-trends`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryOverdueInterventions: (sessionId: string) =>
      requestJson<MemoryOverdueInterventionsResponse>(baseUrl, `/sessions/${sessionId}/memory-overdue-interventions`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryOverdueEscalationLanes: (sessionId: string) =>
      requestJson<MemoryOverdueEscalationLanesResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-escalation-lanes`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRecoveryPaths: (sessionId: string) =>
      requestJson<MemoryOverdueRecoveryPathsResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-recovery-paths`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueResolutionCheckpoints: (sessionId: string) =>
      requestJson<MemoryOverdueResolutionCheckpointsResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-resolution-checkpoints`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueResolutionOutcomes: (sessionId: string) =>
      requestJson<MemoryOverdueResolutionOutcomesResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-resolution-outcomes`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueClosureDecisions: (sessionId: string) =>
      requestJson<MemoryOverdueClosureDecisionsResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-closure-decisions`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueArchiveRecommendations: (sessionId: string) =>
      requestJson<MemoryOverdueArchiveRecommendationsResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-archive-recommendations`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionGuidance: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionGuidanceResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-guidance`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionWindows: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionWindowsResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-windows`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreaches: (sessionId: string) =>
      requestJson<MemoryOverdueBreachesResponse>(baseUrl, `/sessions/${sessionId}/memory-overdue-breaches`, {
        method: "POST",
        authToken,
        body: withScopeBody(userId, tenantId),
      }),
    memoryOverdueRetentionBreachAging: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachAgingResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-aging`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreachActions: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachActionsResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-actions`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreachLanes: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachLanesResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-lanes`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreachOwnerTargets: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachOwnerTargetsResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-owner-targets`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreachFollowThroughModes: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachFollowThroughModesResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-follow-through-modes`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreachFollowThroughOutcomes: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachFollowThroughOutcomesResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-follow-through-outcomes`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreachFollowThroughCompletionStates: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachFollowThroughCompletionStatesResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-follow-through-completion-states`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreachFollowThroughVerificationStates: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachFollowThroughVerificationStatesResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-follow-through-verification-states`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
    memoryOverdueRetentionBreachFollowThroughVerificationOutcomes: (sessionId: string) =>
      requestJson<MemoryOverdueRetentionBreachFollowThroughVerificationOutcomesResponse>(
        baseUrl,
        `/sessions/${sessionId}/memory-overdue-retention-breach-follow-through-verification-outcomes`,
        {
          method: "POST",
          authToken,
          body: withScopeBody(userId, tenantId),
        },
      ),
  };
}
