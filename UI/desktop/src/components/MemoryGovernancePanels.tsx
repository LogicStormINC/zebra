import { Space, Statistic, Tag } from "antd";
import type {
  MemoryActionHintsResponse,
  MemoryEscalationsResponse,
  MemoryFollowUpWindowsResponse,
  MemoryGovernanceSignalsResponse,
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
  MemoryOverdueAgeBucketsResponse,
  MemoryOverdueArchiveRecommendationsResponse,
  MemoryOverdueClosureDecisionsResponse,
  MemoryOverdueEscalationLanesResponse,
  MemoryOverdueFlagsResponse,
  MemoryOverdueInterventionsResponse,
  MemoryOverdueRecoveryPathsResponse,
  MemoryOverdueRetentionGuidanceResponse,
  MemoryOverdueRetentionWindowsResponse,
  MemoryOverdueResolutionCheckpointsResponse,
  MemoryOverdueResolutionOutcomesResponse,
  MemoryOverdueTrendSignalsResponse,
  MemoryOverdueTypeRollupsResponse,
  MemoryOverdueVisibilityRollupsResponse,
  MemoryPressureSignalsResponse,
} from "../types";
import { MemoryGovernanceAlerts } from "./MemoryGovernanceAlerts";
import { MemoryGovernanceScopeList } from "./MemoryGovernanceScopeList";

export interface MemoryGovernancePanelsProps {
  governance: MemoryGovernanceSignalsResponse;
  actionHints: MemoryActionHintsResponse;
  pressure: MemoryPressureSignalsResponse;
  escalations: MemoryEscalationsResponse;
  followUp: MemoryFollowUpWindowsResponse;
  overdue: MemoryOverdueFlagsResponse;
  overdueAge: MemoryOverdueAgeBucketsResponse;
  overdueType: MemoryOverdueTypeRollupsResponse;
  overdueVisibility: MemoryOverdueVisibilityRollupsResponse;
  overdueTrends: MemoryOverdueTrendSignalsResponse;
  overdueInterventions: MemoryOverdueInterventionsResponse;
  overdueRetentionBreaches: MemoryOverdueBreachesResponse;
  overdueRetentionBreachAging: MemoryOverdueRetentionBreachAgingResponse;
  overdueRetentionBreachActions: MemoryOverdueRetentionBreachActionsResponse;
  overdueRetentionBreachLanes: MemoryOverdueRetentionBreachLanesResponse;
  overdueRetentionBreachOwnerTargets: MemoryOverdueRetentionBreachOwnerTargetsResponse;
  overdueRetentionBreachFollowThroughModes: MemoryOverdueRetentionBreachFollowThroughModesResponse;
  overdueRetentionBreachFollowThroughOutcomes: MemoryOverdueRetentionBreachFollowThroughOutcomesResponse;
  overdueRetentionBreachFollowThroughCompletionStates: MemoryOverdueRetentionBreachFollowThroughCompletionStatesResponse;
  overdueRetentionBreachFollowThroughVerificationStates: MemoryOverdueRetentionBreachFollowThroughVerificationStatesResponse;
  overdueRetentionBreachFollowThroughVerificationOutcomes: MemoryOverdueRetentionBreachFollowThroughVerificationOutcomesResponse;
  overdueEscalationLanes: MemoryOverdueEscalationLanesResponse;
  overdueRecoveryPaths: MemoryOverdueRecoveryPathsResponse;
  overdueResolutionCheckpoints: MemoryOverdueResolutionCheckpointsResponse;
  overdueResolutionOutcomes: MemoryOverdueResolutionOutcomesResponse;
  overdueClosureDecisions: MemoryOverdueClosureDecisionsResponse;
  overdueArchiveRecommendations: MemoryOverdueArchiveRecommendationsResponse;
  overdueRetentionGuidance: MemoryOverdueRetentionGuidanceResponse;
  overdueRetentionWindows: MemoryOverdueRetentionWindowsResponse;
}

export interface MemoryGovernanceScopeSignals {
  action?: MemoryActionHintsResponse["scopes"][number];
  pressure?: MemoryPressureSignalsResponse["scopes"][number];
  escalation?: MemoryEscalationsResponse["scopes"][number];
  followUp?: MemoryFollowUpWindowsResponse["scopes"][number];
  overdue?: MemoryOverdueFlagsResponse["scopes"][number];
  overdueAge?: MemoryOverdueAgeBucketsResponse["scopes"][number];
  overdueType?: MemoryOverdueTypeRollupsResponse["scopes"][number];
  overdueVisibility?: MemoryOverdueVisibilityRollupsResponse["scopes"][number];
  overdueTrend?: MemoryOverdueTrendSignalsResponse["scopes"][number];
  overdueIntervention?: MemoryOverdueInterventionsResponse["scopes"][number];
  overdueEscalationLane?: MemoryOverdueEscalationLanesResponse["scopes"][number];
  overdueRecoveryPath?: MemoryOverdueRecoveryPathsResponse["scopes"][number];
  overdueResolutionCheckpoint?: MemoryOverdueResolutionCheckpointsResponse["scopes"][number];
  overdueResolutionOutcome?: MemoryOverdueResolutionOutcomesResponse["scopes"][number];
  overdueClosureDecision?: MemoryOverdueClosureDecisionsResponse["scopes"][number];
  overdueArchiveRecommendation?: MemoryOverdueArchiveRecommendationsResponse["scopes"][number];
  overdueRetentionGuidance?: MemoryOverdueRetentionGuidanceResponse["scopes"][number];
  overdueRetentionWindow?: MemoryOverdueRetentionWindowsResponse["scopes"][number];
  overdueRetentionBreach?: MemoryOverdueBreachesResponse["scopes"][number];
  overdueRetentionBreachAge?: MemoryOverdueRetentionBreachAgingResponse["scopes"][number];
  overdueRetentionBreachAction?: MemoryOverdueRetentionBreachActionsResponse["scopes"][number];
  overdueRetentionBreachLane?: MemoryOverdueRetentionBreachLanesResponse["scopes"][number];
  overdueRetentionBreachOwnerTarget?: MemoryOverdueRetentionBreachOwnerTargetsResponse["scopes"][number];
  overdueRetentionBreachFollowThroughMode?: MemoryOverdueRetentionBreachFollowThroughModesResponse["scopes"][number];
  overdueRetentionBreachFollowThroughOutcome?:
    MemoryOverdueRetentionBreachFollowThroughOutcomesResponse["scopes"][number];
  overdueRetentionBreachFollowThroughCompletionState?:
    MemoryOverdueRetentionBreachFollowThroughCompletionStatesResponse["scopes"][number];
  overdueRetentionBreachFollowThroughVerificationState?:
    MemoryOverdueRetentionBreachFollowThroughVerificationStatesResponse["scopes"][number];
  overdueRetentionBreachFollowThroughVerificationOutcome?:
    MemoryOverdueRetentionBreachFollowThroughVerificationOutcomesResponse["scopes"][number];
}

export function MemoryGovernancePanels(props: MemoryGovernancePanelsProps) {
  const scopeSignals = buildScopeSignals(props);

  return (
    <>
      <Space size="large" wrap>
        <Statistic title="Pending" value={props.governance.total_pending_count} />
        <Statistic title="Reviewed" value={props.governance.total_reviewed_count} />
        <Statistic title="Scopes" value={props.governance.scope_count} />
        <Statistic title="Reviewed 24h" value={props.pressure.total_reviewed_last_24h_count} />
        <Statistic title="Overdue scopes" value={props.overdue.overdue_scope_count} />
      </Space>
      <Space wrap>
        <Tag color="orange">{props.actionHints.highest_priority_action_hint ?? "no_action_needed"}</Tag>
        <Tag color="red">{props.actionHints.highest_priority_action_priority ?? "none"}</Tag>
        <Tag color="volcano">{props.pressure.highest_pressure_level ?? "clear"}</Tag>
        <Tag color="magenta">{props.escalations.highest_priority_escalation_recommendation ?? "no_escalation_needed"}</Tag>
        <Tag color="cyan">{props.followUp.highest_priority_follow_up_window ?? "no_follow_up"}</Tag>
        <Tag color="red">{props.overdue.highest_priority_overdue_priority ?? "no_overdue"}</Tag>
        <Tag color="gold">{props.overdueAge.highest_priority_overdue_age_bucket ?? "not_overdue"}</Tag>
        <Tag color="lime">{props.overdueType.highest_priority_overdue_memory_type ?? "no_overdue_type"}</Tag>
        <Tag color="red">{props.overdueRetentionBreaches.highest_priority_overdue_retention_breach ?? "no_breach"}</Tag>
        <Tag color="volcano">
          {props.overdueRetentionBreachAging.highest_priority_overdue_retention_breach_age_bucket ?? "no_breach_age"}
        </Tag>
        <Tag color="orange">
          {props.overdueRetentionBreachActions.highest_priority_overdue_retention_breach_action ?? "no_breach_action"}
        </Tag>
        <Tag color="blue">
          {props.overdueRetentionBreachLanes.highest_priority_overdue_retention_breach_lane ?? "no_breach_lane"}
        </Tag>
        <Tag color="geekblue">
          {props.overdueRetentionBreachOwnerTargets.highest_priority_overdue_retention_breach_owner_target ??
            "no_breach_owner_target"}
        </Tag>
        <Tag color="gold">
          {props.overdueRetentionBreachFollowThroughModes.highest_priority_overdue_retention_breach_follow_through_mode ??
            "no_breach_follow_through_mode"}
        </Tag>
        <Tag color="cyan">
          {props.overdueRetentionBreachFollowThroughOutcomes.highest_priority_overdue_retention_breach_follow_through_outcome ??
            "no_breach_follow_through_outcome"}
        </Tag>
        <Tag color="magenta">
          {props.overdueRetentionBreachFollowThroughCompletionStates.highest_priority_overdue_retention_breach_follow_through_completion_state ??
            "no_breach_follow_through_completion_state"}
        </Tag>
        <Tag color="green">
          {props.overdueRetentionBreachFollowThroughVerificationStates.highest_priority_overdue_retention_breach_follow_through_verification_state ??
            "no_breach_follow_through_verification_state"}
        </Tag>
        <Tag color="orange">
          {props.overdueRetentionBreachFollowThroughVerificationOutcomes.highest_priority_overdue_retention_breach_follow_through_verification_outcome ??
            "no_breach_follow_through_verification_outcome"}
        </Tag>
        <Tag color="green">
          {props.overdueVisibility.highest_priority_overdue_memory_visibility ?? "no_overdue_visibility"}
        </Tag>
        <Tag color="blue">{props.overdueTrends.highest_priority_overdue_trend_signal ?? "stable"}</Tag>
        <Tag color="purple">
          {props.overdueInterventions.highest_priority_overdue_intervention_hint ?? "no_intervention"}
        </Tag>
        <Tag color="volcano">
          {props.overdueEscalationLanes.highest_priority_overdue_escalation_lane ?? "no_escalation_lane"}
        </Tag>
        <Tag color="cyan">
          {props.overdueRecoveryPaths.highest_priority_overdue_recovery_path ?? "no_recovery_path"}
        </Tag>
        <Tag color="gold">
          {props.overdueResolutionCheckpoints.highest_priority_overdue_resolution_checkpoint ??
            "no_resolution_checkpoint"}
        </Tag>
        <Tag color="green">
          {props.overdueResolutionOutcomes.highest_priority_overdue_resolution_outcome ?? "no_resolution_outcome"}
        </Tag>
        <Tag color="orange">
          {props.overdueClosureDecisions.highest_priority_overdue_closure_decision ?? "no_closure_decision"}
        </Tag>
        <Tag color="magenta">
          {props.overdueArchiveRecommendations.highest_priority_overdue_archive_recommendation ?? "no_archive_guidance"}
        </Tag>
        <Tag color="lime">
          {props.overdueRetentionGuidance.highest_priority_overdue_retention_guidance ?? "no_retention_guidance"}
        </Tag>
        <Tag color="geekblue">
          {props.overdueRetentionWindows.highest_priority_overdue_retention_window ?? "no_retention_window"}
        </Tag>
      </Space>
      <MemoryGovernanceAlerts
        actionReasons={props.actionHints.highest_priority_action_reasons}
        pressureReasons={props.pressure.highest_pressure_reasons}
        followUpReasons={props.followUp.highest_priority_follow_up_reasons}
        overdueReasons={props.overdue.highest_priority_overdue_reasons}
        overdueAgeReasons={props.overdueAge.highest_priority_overdue_age_reasons}
        overdueTrendReasons={props.overdueTrends.highest_priority_overdue_trend_reasons}
        overdueInterventionReasons={props.overdueInterventions.highest_priority_overdue_intervention_reasons}
        overdueEscalationReasons={props.overdueEscalationLanes.highest_priority_overdue_escalation_reasons}
        overdueRecoveryReasons={props.overdueRecoveryPaths.highest_priority_overdue_recovery_reasons}
        overdueResolutionReasons={props.overdueResolutionCheckpoints.highest_priority_overdue_resolution_reasons}
        overdueOutcomeReasons={props.overdueResolutionOutcomes.highest_priority_overdue_resolution_outcome_reasons}
        overdueClosureReasons={props.overdueClosureDecisions.highest_priority_overdue_closure_reasons}
        overdueArchiveReasons={props.overdueArchiveRecommendations.highest_priority_overdue_archive_reasons}
        overdueRetentionReasons={props.overdueRetentionGuidance.highest_priority_overdue_retention_reasons}
        overdueRetentionWindowReasons={props.overdueRetentionWindows.highest_priority_overdue_retention_window_reasons}
        overdueRetentionBreachReasons={props.overdueRetentionBreaches.highest_priority_overdue_retention_breach_reasons}
        overdueRetentionBreachAgeReasons={props.overdueRetentionBreachAging.highest_priority_overdue_retention_breach_age_reasons}
        overdueRetentionBreachActionReasons={props.overdueRetentionBreachActions.highest_priority_overdue_retention_breach_action_reasons}
        overdueRetentionBreachLaneReasons={props.overdueRetentionBreachLanes.highest_priority_overdue_retention_breach_lane_reasons}
        overdueRetentionBreachOwnerTargetReasons={
          props.overdueRetentionBreachOwnerTargets.highest_priority_overdue_retention_breach_owner_target_reasons
        }
        overdueRetentionBreachFollowThroughModeReasons={
          props.overdueRetentionBreachFollowThroughModes.highest_priority_overdue_retention_breach_follow_through_reasons
        }
        overdueRetentionBreachFollowThroughOutcomeReasons={
          props.overdueRetentionBreachFollowThroughOutcomes.highest_priority_overdue_retention_breach_follow_through_outcome_reasons
        }
        overdueRetentionBreachCompletionStateReasons={
          props.overdueRetentionBreachFollowThroughCompletionStates
            .highest_priority_overdue_retention_breach_follow_through_completion_reasons
        }
        overdueRetentionBreachVerificationStateReasons={
          props.overdueRetentionBreachFollowThroughVerificationStates
            .highest_priority_overdue_retention_breach_follow_through_verification_reasons
        }
        overdueRetentionBreachVerificationOutcomeReasons={
          props.overdueRetentionBreachFollowThroughVerificationOutcomes
            .highest_priority_overdue_retention_breach_follow_through_verification_outcome_reasons
        }
      />
      <MemoryGovernanceScopeList scopes={props.governance.scopes} scopeSignals={scopeSignals} />
    </>
  );
}

function buildScopeSignals(props: MemoryGovernancePanelsProps) {
  const map = new Map<string, Record<string, object>>();
  const assign = (scopeKind: string, scopeId: string, field: string, value: object) => {
    const key = `${scopeKind}:${scopeId}`;
    map.set(key, { ...(map.get(key) ?? {}), [field]: value });
  };

  for (const scope of props.actionHints.scopes) assign(scope.scope_kind, scope.scope_id, "action", scope);
  for (const scope of props.pressure.scopes) assign(scope.scope_kind, scope.scope_id, "pressure", scope);
  for (const scope of props.escalations.scopes) assign(scope.scope_kind, scope.scope_id, "escalation", scope);
  for (const scope of props.followUp.scopes) assign(scope.scope_kind, scope.scope_id, "followUp", scope);
  for (const scope of props.overdue.scopes) assign(scope.scope_kind, scope.scope_id, "overdue", scope);
  for (const scope of props.overdueAge.scopes) assign(scope.scope_kind, scope.scope_id, "overdueAge", scope);
  for (const scope of props.overdueType.scopes) assign(scope.scope_kind, scope.scope_id, "overdueType", scope);
  for (const scope of props.overdueVisibility.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueVisibility", scope);
  }
  for (const scope of props.overdueTrends.scopes) assign(scope.scope_kind, scope.scope_id, "overdueTrend", scope);
  for (const scope of props.overdueInterventions.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueIntervention", scope);
  }
  for (const scope of props.overdueEscalationLanes.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueEscalationLane", scope);
  }
  for (const scope of props.overdueRecoveryPaths.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRecoveryPath", scope);
  }
  for (const scope of props.overdueResolutionCheckpoints.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueResolutionCheckpoint", scope);
  }
  for (const scope of props.overdueResolutionOutcomes.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueResolutionOutcome", scope);
  }
  for (const scope of props.overdueClosureDecisions.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueClosureDecision", scope);
  }
  for (const scope of props.overdueArchiveRecommendations.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueArchiveRecommendation", scope);
  }
  for (const scope of props.overdueRetentionGuidance.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionGuidance", scope);
  }
  for (const scope of props.overdueRetentionWindows.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionWindow", scope);
  }
  for (const scope of props.overdueRetentionBreaches.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionBreach", scope);
  }
  for (const scope of props.overdueRetentionBreachAging.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionBreachAge", scope);
  }
  for (const scope of props.overdueRetentionBreachActions.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionBreachAction", scope);
  }
  for (const scope of props.overdueRetentionBreachLanes.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionBreachLane", scope);
  }
  for (const scope of props.overdueRetentionBreachOwnerTargets.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionBreachOwnerTarget", scope);
  }
  for (const scope of props.overdueRetentionBreachFollowThroughModes.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionBreachFollowThroughMode", scope);
  }
  for (const scope of props.overdueRetentionBreachFollowThroughOutcomes.scopes) {
    assign(scope.scope_kind, scope.scope_id, "overdueRetentionBreachFollowThroughOutcome", scope);
  }
  for (const scope of props.overdueRetentionBreachFollowThroughCompletionStates.scopes) {
    assign(
      scope.scope_kind,
      scope.scope_id,
      "overdueRetentionBreachFollowThroughCompletionState",
      scope,
    );
  }
  for (const scope of props.overdueRetentionBreachFollowThroughVerificationStates.scopes) {
    assign(
      scope.scope_kind,
      scope.scope_id,
      "overdueRetentionBreachFollowThroughVerificationState",
      scope,
    );
  }
  for (const scope of props.overdueRetentionBreachFollowThroughVerificationOutcomes.scopes) {
    assign(
      scope.scope_kind,
      scope.scope_id,
      "overdueRetentionBreachFollowThroughVerificationOutcome",
      scope,
    );
  }

  return map as Map<string, MemoryGovernanceScopeSignals>;
}
