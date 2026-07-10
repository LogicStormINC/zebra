import { Alert, Button, Card, Space, Spin, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { createStyles } from "antd-style";
import type { ZebraApiClient } from "../lib/zebra-api";
import { MemoryGovernancePanels } from "./MemoryGovernancePanels";
import { useMemoryGovernanceSurface } from "../lib/use-memory-governance-surface";

const useStyle = createStyles(({ css }) => ({
  secondaryText: css`
    margin-bottom: 0;
    color: rgba(255, 255, 255, 0.58) !important;
  `,
  loadingArea: css`
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: calc(var(--zebra-space-xl) + var(--zebra-space-xl));
  `,
}));

interface MemoryGovernanceCardProps {
  api: ZebraApiClient;
  sessionId: string;
  authToken: string;
  apiBaseUrl: string;
}

export function MemoryGovernanceCard(props: MemoryGovernanceCardProps) {
  const surface = useMemoryGovernanceSurface(props);
  const { styles } = useStyle();

  return (
    <Card
      title="Memory Governance"
      extra={
        <Button
          icon={<ReloadOutlined />}
          onClick={surface.refresh}
          disabled={!props.sessionId.trim()}
        >
          Refresh
        </Button>
      }
    >
      <Space direction="vertical" size="large" className="w-full">
        <Typography.Paragraph className={styles.secondaryText}>
          Read backlog health, review status, and highest-priority memory action before doing queue review.
        </Typography.Paragraph>
        {!props.sessionId.trim() ? (
          <Alert
            type="info"
            showIcon
            message="No active session"
            description="Select or create a session first so governance signals can resolve repo scope."
          />
        ) : null}
        {surface.errorText ? (
          <Alert
            type="warning"
            showIcon
            message="Governance signals unavailable"
            description={surface.errorText}
          />
        ) : null}
        {surface.isLoading ? (
          <div className={styles.loadingArea}>
            <Spin />
          </div>
        ) : null}
        {surface.governanceQuery.data &&
        surface.actionHintsQuery.data &&
        surface.pressureQuery.data &&
        surface.escalationsQuery.data &&
        surface.followUpQuery.data &&
        surface.overdueRetentionBreachesQuery.data &&
        surface.overdueRetentionBreachAgingQuery.data &&
        surface.overdueRetentionBreachActionsQuery.data &&
        surface.overdueRetentionBreachLanesQuery.data &&
        surface.overdueRetentionBreachOwnerTargetsQuery.data &&
        surface.overdueRetentionBreachFollowThroughModesQuery.data &&
        surface.overdueRetentionBreachFollowThroughOutcomesQuery.data &&
        surface.overdueRetentionBreachFollowThroughCompletionStatesQuery.data &&
        surface.overdueRetentionBreachFollowThroughVerificationStatesQuery.data &&
        surface.overdueRetentionBreachFollowThroughVerificationOutcomesQuery.data &&
        surface.overdueQuery.data &&
        surface.overdueAgeQuery.data &&
        surface.overdueTypeQuery.data &&
        surface.overdueVisibilityQuery.data &&
        surface.overdueTrendsQuery.data &&
        surface.overdueInterventionsQuery.data &&
        surface.overdueEscalationLanesQuery.data &&
        surface.overdueRecoveryPathsQuery.data &&
        surface.overdueResolutionCheckpointsQuery.data &&
        surface.overdueResolutionOutcomesQuery.data &&
        surface.overdueClosureDecisionsQuery.data &&
        surface.overdueArchiveRecommendationsQuery.data &&
        surface.overdueRetentionGuidanceQuery.data &&
        surface.overdueRetentionWindowsQuery.data ? (
          <MemoryGovernancePanels
            governance={surface.governanceQuery.data}
            actionHints={surface.actionHintsQuery.data}
            pressure={surface.pressureQuery.data}
            escalations={surface.escalationsQuery.data}
            followUp={surface.followUpQuery.data}
            overdueRetentionBreaches={surface.overdueRetentionBreachesQuery.data}
            overdueRetentionBreachAging={surface.overdueRetentionBreachAgingQuery.data}
            overdueRetentionBreachActions={surface.overdueRetentionBreachActionsQuery.data}
            overdueRetentionBreachLanes={surface.overdueRetentionBreachLanesQuery.data}
            overdueRetentionBreachOwnerTargets={surface.overdueRetentionBreachOwnerTargetsQuery.data}
            overdueRetentionBreachFollowThroughModes={surface.overdueRetentionBreachFollowThroughModesQuery.data}
            overdueRetentionBreachFollowThroughOutcomes={
              surface.overdueRetentionBreachFollowThroughOutcomesQuery.data
            }
            overdueRetentionBreachFollowThroughCompletionStates={
              surface.overdueRetentionBreachFollowThroughCompletionStatesQuery.data
            }
            overdueRetentionBreachFollowThroughVerificationStates={
              surface.overdueRetentionBreachFollowThroughVerificationStatesQuery.data
            }
            overdueRetentionBreachFollowThroughVerificationOutcomes={
              surface.overdueRetentionBreachFollowThroughVerificationOutcomesQuery.data
            }
            overdue={surface.overdueQuery.data}
            overdueAge={surface.overdueAgeQuery.data}
            overdueType={surface.overdueTypeQuery.data}
            overdueVisibility={surface.overdueVisibilityQuery.data}
            overdueTrends={surface.overdueTrendsQuery.data}
            overdueInterventions={surface.overdueInterventionsQuery.data}
            overdueEscalationLanes={surface.overdueEscalationLanesQuery.data}
            overdueRecoveryPaths={surface.overdueRecoveryPathsQuery.data}
            overdueResolutionCheckpoints={surface.overdueResolutionCheckpointsQuery.data}
            overdueResolutionOutcomes={surface.overdueResolutionOutcomesQuery.data}
            overdueClosureDecisions={surface.overdueClosureDecisionsQuery.data}
            overdueArchiveRecommendations={surface.overdueArchiveRecommendationsQuery.data}
            overdueRetentionGuidance={surface.overdueRetentionGuidanceQuery.data}
            overdueRetentionWindows={surface.overdueRetentionWindowsQuery.data}
          />
        ) : null}
      </Space>
    </Card>
  );
}
