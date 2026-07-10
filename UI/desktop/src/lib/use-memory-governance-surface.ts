import { useQuery } from "@tanstack/react-query";
import type { ZebraApiClient } from "./zebra-api";
import { formatOperatorError } from "./use-operator-workbench";
import type {
  MemoryOverdueBreachesResponse,
  MemoryOverdueRetentionBreachAgingResponse,
  MemoryOverdueRetentionBreachActionsResponse,
  MemoryOverdueRetentionBreachFollowThroughCompletionStatesResponse,
  MemoryOverdueRetentionBreachFollowThroughModesResponse,
  MemoryOverdueRetentionBreachFollowThroughOutcomesResponse,
  MemoryOverdueRetentionBreachFollowThroughVerificationOutcomesResponse,
  MemoryOverdueRetentionBreachFollowThroughVerificationStatesResponse,
  MemoryOverdueRetentionBreachLanesResponse,
  MemoryOverdueRetentionBreachOwnerTargetsResponse,
} from "../types";

interface UseMemoryGovernanceSurfaceParams {
  api: ZebraApiClient;
  sessionId: string;
  authToken: string;
  apiBaseUrl: string;
}

export function useMemoryGovernanceSurface({
  api,
  sessionId,
  authToken,
  apiBaseUrl,
}: UseMemoryGovernanceSurfaceParams) {
  const normalizedSessionId = sessionId.trim();
  const enabled = !!normalizedSessionId;

  const governanceQuery = useQuery({
    queryKey: ["memory-governance", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryGovernance(normalizedSessionId),
    enabled,
  });
  const actionHintsQuery = useQuery({
    queryKey: ["memory-action-hints", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryActionHints(normalizedSessionId),
    enabled,
  });
  const pressureQuery = useQuery({
    queryKey: ["memory-pressure", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryPressure(normalizedSessionId),
    enabled,
  });
  const escalationsQuery = useQuery({
    queryKey: ["memory-escalations", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryEscalations(normalizedSessionId),
    enabled,
  });
  const followUpQuery = useQuery({
    queryKey: ["memory-follow-up-windows", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryFollowUpWindows(normalizedSessionId),
    enabled,
  });
  const overdueQuery = useQuery({
    queryKey: ["memory-overdue-flags", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueFlags(normalizedSessionId),
    enabled,
  });
  const overdueAgeQuery = useQuery({
    queryKey: ["memory-overdue-age-buckets", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueAgeBuckets(normalizedSessionId),
    enabled,
  });
  const overdueTypeQuery = useQuery({
    queryKey: ["memory-overdue-types", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueTypes(normalizedSessionId),
    enabled,
  });
  const overdueVisibilityQuery = useQuery({
    queryKey: ["memory-overdue-visibility", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueVisibility(normalizedSessionId),
    enabled,
  });
  const overdueTrendsQuery = useQuery({
    queryKey: ["memory-overdue-trends", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueTrends(normalizedSessionId),
    enabled,
  });
  const overdueInterventionsQuery = useQuery({
    queryKey: ["memory-overdue-interventions", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueInterventions(normalizedSessionId),
    enabled,
  });
  const overdueEscalationLanesQuery = useQuery({
    queryKey: ["memory-overdue-escalation-lanes", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueEscalationLanes(normalizedSessionId),
    enabled,
  });
  const overdueRecoveryPathsQuery = useQuery({
    queryKey: ["memory-overdue-recovery-paths", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueRecoveryPaths(normalizedSessionId),
    enabled,
  });
  const overdueResolutionCheckpointsQuery = useQuery({
    queryKey: ["memory-overdue-resolution-checkpoints", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueResolutionCheckpoints(normalizedSessionId),
    enabled,
  });
  const overdueResolutionOutcomesQuery = useQuery({
    queryKey: ["memory-overdue-resolution-outcomes", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueResolutionOutcomes(normalizedSessionId),
    enabled,
  });
  const overdueRetentionBreachesQuery = useQuery<MemoryOverdueBreachesResponse>({
    queryKey: ["memory-overdue-retention-breaches", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueRetentionBreaches(normalizedSessionId),
    enabled,
  });
  const overdueRetentionBreachAgingQuery = useQuery<MemoryOverdueRetentionBreachAgingResponse>({
    queryKey: [
      "memory-overdue-retention-breach-aging",
      apiBaseUrl,
      authToken,
      normalizedSessionId,
    ],
    queryFn: () => api.memoryOverdueRetentionBreachAging(normalizedSessionId),
    enabled,
  });
  const overdueRetentionBreachActionsQuery = useQuery<MemoryOverdueRetentionBreachActionsResponse>({
    queryKey: [
      "memory-overdue-retention-breach-actions",
      apiBaseUrl,
      authToken,
      normalizedSessionId,
    ],
    queryFn: () => api.memoryOverdueRetentionBreachActions(normalizedSessionId),
    enabled,
  });
  const overdueRetentionBreachLanesQuery = useQuery<MemoryOverdueRetentionBreachLanesResponse>({
    queryKey: [
      "memory-overdue-retention-breach-lanes",
      apiBaseUrl,
      authToken,
      normalizedSessionId,
    ],
    queryFn: () => api.memoryOverdueRetentionBreachLanes(normalizedSessionId),
    enabled,
  });
  const overdueRetentionBreachOwnerTargetsQuery = useQuery<MemoryOverdueRetentionBreachOwnerTargetsResponse>({
    queryKey: [
      "memory-overdue-retention-breach-owner-targets",
      apiBaseUrl,
      authToken,
      normalizedSessionId,
    ],
    queryFn: () => api.memoryOverdueRetentionBreachOwnerTargets(normalizedSessionId),
    enabled,
  });
  const overdueRetentionBreachFollowThroughModesQuery =
    useQuery<MemoryOverdueRetentionBreachFollowThroughModesResponse>({
      queryKey: [
        "memory-overdue-retention-breach-follow-through-modes",
        apiBaseUrl,
        authToken,
        normalizedSessionId,
      ],
      queryFn: () => api.memoryOverdueRetentionBreachFollowThroughModes(normalizedSessionId),
      enabled,
    });
  const overdueRetentionBreachFollowThroughOutcomesQuery =
    useQuery<MemoryOverdueRetentionBreachFollowThroughOutcomesResponse>({
      queryKey: [
        "memory-overdue-retention-breach-follow-through-outcomes",
        apiBaseUrl,
        authToken,
        normalizedSessionId,
      ],
      queryFn: () => api.memoryOverdueRetentionBreachFollowThroughOutcomes(normalizedSessionId),
      enabled,
    });
  const overdueRetentionBreachFollowThroughCompletionStatesQuery =
    useQuery<MemoryOverdueRetentionBreachFollowThroughCompletionStatesResponse>({
      queryKey: [
        "memory-overdue-retention-breach-follow-through-completion-states",
        apiBaseUrl,
        authToken,
        normalizedSessionId,
      ],
      queryFn: () => api.memoryOverdueRetentionBreachFollowThroughCompletionStates(normalizedSessionId),
      enabled,
    });
  const overdueRetentionBreachFollowThroughVerificationStatesQuery =
    useQuery<MemoryOverdueRetentionBreachFollowThroughVerificationStatesResponse>({
      queryKey: [
        "memory-overdue-retention-breach-follow-through-verification-states",
        apiBaseUrl,
        authToken,
        normalizedSessionId,
      ],
      queryFn: () => api.memoryOverdueRetentionBreachFollowThroughVerificationStates(normalizedSessionId),
      enabled,
    });
  const overdueRetentionBreachFollowThroughVerificationOutcomesQuery =
    useQuery<MemoryOverdueRetentionBreachFollowThroughVerificationOutcomesResponse>({
      queryKey: [
        "memory-overdue-retention-breach-follow-through-verification-outcomes",
        apiBaseUrl,
        authToken,
        normalizedSessionId,
      ],
      queryFn: () => api.memoryOverdueRetentionBreachFollowThroughVerificationOutcomes(normalizedSessionId),
      enabled,
    });
  const overdueClosureDecisionsQuery = useQuery({
    queryKey: ["memory-overdue-closure-decisions", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueClosureDecisions(normalizedSessionId),
    enabled,
  });
  const overdueArchiveRecommendationsQuery = useQuery({
    queryKey: ["memory-overdue-archive-recommendations", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueArchiveRecommendations(normalizedSessionId),
    enabled,
  });
  const overdueRetentionGuidanceQuery = useQuery({
    queryKey: ["memory-overdue-retention-guidance", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueRetentionGuidance(normalizedSessionId),
    enabled,
  });
  const overdueRetentionWindowsQuery = useQuery({
    queryKey: ["memory-overdue-retention-windows", apiBaseUrl, authToken, normalizedSessionId],
    queryFn: () => api.memoryOverdueRetentionWindows(normalizedSessionId),
    enabled,
  });

  const queries = [
    governanceQuery,
    actionHintsQuery,
    pressureQuery,
    escalationsQuery,
    followUpQuery,
    overdueQuery,
    overdueAgeQuery,
    overdueTypeQuery,
    overdueVisibilityQuery,
    overdueTrendsQuery,
    overdueInterventionsQuery,
    overdueEscalationLanesQuery,
    overdueRecoveryPathsQuery,
    overdueResolutionCheckpointsQuery,
    overdueResolutionOutcomesQuery,
    overdueRetentionBreachesQuery,
    overdueRetentionBreachAgingQuery,
    overdueRetentionBreachActionsQuery,
    overdueRetentionBreachLanesQuery,
    overdueRetentionBreachOwnerTargetsQuery,
    overdueRetentionBreachFollowThroughModesQuery,
    overdueRetentionBreachFollowThroughOutcomesQuery,
    overdueRetentionBreachFollowThroughCompletionStatesQuery,
    overdueRetentionBreachFollowThroughVerificationStatesQuery,
    overdueRetentionBreachFollowThroughVerificationOutcomesQuery,
    overdueClosureDecisionsQuery,
    overdueArchiveRecommendationsQuery,
    overdueRetentionGuidanceQuery,
    overdueRetentionWindowsQuery,
  ];

  return {
    governanceQuery,
    actionHintsQuery,
    pressureQuery,
    escalationsQuery,
    followUpQuery,
    overdueQuery,
    overdueAgeQuery,
    overdueTypeQuery,
    overdueVisibilityQuery,
    overdueTrendsQuery,
    overdueInterventionsQuery,
    overdueEscalationLanesQuery,
    overdueRecoveryPathsQuery,
    overdueResolutionCheckpointsQuery,
    overdueResolutionOutcomesQuery,
    overdueRetentionBreachesQuery,
    overdueRetentionBreachAgingQuery,
    overdueRetentionBreachActionsQuery,
    overdueRetentionBreachLanesQuery,
    overdueRetentionBreachOwnerTargetsQuery,
    overdueRetentionBreachFollowThroughModesQuery,
    overdueRetentionBreachFollowThroughOutcomesQuery,
    overdueRetentionBreachFollowThroughCompletionStatesQuery,
    overdueRetentionBreachFollowThroughVerificationStatesQuery,
    overdueRetentionBreachFollowThroughVerificationOutcomesQuery,
    overdueClosureDecisionsQuery,
    overdueArchiveRecommendationsQuery,
    overdueRetentionGuidanceQuery,
    overdueRetentionWindowsQuery,
    isLoading: queries.some((query) => query.isLoading),
    errorText: formatFirstQueryError(queries.map((query) => query.error)),
    refresh: () => {
      for (const query of queries) {
        void query.refetch();
      }
    },
  };
}

function formatFirstQueryError(errors: Array<Error | null>) {
  for (const error of errors) {
    if (error) {
      return formatOperatorError(error);
    }
  }
  return null;
}
