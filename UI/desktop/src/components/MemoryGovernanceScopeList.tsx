import { List, Space, Tag, Typography } from "antd";
import type { MemoryGovernanceSignalsResponse } from "../types";
import type { MemoryGovernanceScopeSignals } from "./MemoryGovernancePanels";

interface MemoryGovernanceScopeListProps {
  scopes: MemoryGovernanceSignalsResponse["scopes"];
  scopeSignals: Map<string, MemoryGovernanceScopeSignals>;
}

export function MemoryGovernanceScopeList({
  scopes,
  scopeSignals,
}: MemoryGovernanceScopeListProps) {
  return (
    <List
      dataSource={scopes}
      renderItem={(scope) => {
        const signals = scopeSignals.get(`${scope.scope_kind}:${scope.scope_id}`);
        return (
          <List.Item>
            <Space direction="vertical" size={4} className="w-full">
              <Space wrap>
                <Tag color="geekblue">{scope.scope_kind}</Tag>
                <Tag>{scope.scope_id}</Tag>
                <Tag color={scope.queue_status === "pending" ? "orange" : "green"}>{scope.queue_status}</Tag>
                {signals?.action ? <Tag color="purple">{signals.action.action_hint}</Tag> : null}
                {signals?.pressure ? <Tag color="volcano">{signals.pressure.pressure_level}</Tag> : null}
                {signals?.escalation ? <Tag color="magenta">{signals.escalation.escalation_recommendation}</Tag> : null}
                {signals?.followUp ? <Tag color="cyan">{signals.followUp.follow_up_window}</Tag> : null}
                {signals?.overdue?.follow_up_overdue ? <Tag color="red">overdue</Tag> : null}
                {signals?.overdueRetentionBreach?.follow_up_overdue ? (
                  <Tag color="red">overdue_retention_breach</Tag>
                ) : null}
                {signals?.overdueRetentionBreach ? (
                  <Tag color="volcano">breach={signals.overdueRetentionBreach.overdue_retention_breach}</Tag>
                ) : null}
                {signals?.overdueRetentionBreachAge ? (
                  <Tag color="gold">age={signals.overdueRetentionBreachAge.overdue_retention_breach_age_bucket}</Tag>
                ) : null}
                {signals?.overdueRetentionBreachAction ? (
                  <Tag color="purple">action={signals.overdueRetentionBreachAction.overdue_retention_breach_action}</Tag>
                ) : null}
                {signals?.overdueRetentionBreachLane ? (
                  <Tag color="blue">lane={signals.overdueRetentionBreachLane.overdue_retention_breach_lane}</Tag>
                ) : null}
                {signals?.overdueRetentionBreachOwnerTarget ? (
                  <Tag color="cyan">owner={signals.overdueRetentionBreachOwnerTarget.overdue_retention_breach_owner_target}</Tag>
                ) : null}
                {signals?.overdueRetentionBreachFollowThroughMode ? (
                  <Tag color="magenta">mode={signals.overdueRetentionBreachFollowThroughMode.overdue_retention_breach_follow_through_mode}</Tag>
                ) : null}
                {signals?.overdueRetentionBreachFollowThroughOutcome ? (
                  <Tag color="green">outcome={signals.overdueRetentionBreachFollowThroughOutcome.overdue_retention_breach_follow_through_outcome}</Tag>
                ) : null}
                {signals?.overdueRetentionBreachFollowThroughCompletionState ? (
                  <Tag color="orange">completion={
                    signals.overdueRetentionBreachFollowThroughCompletionState
                      .overdue_retention_breach_follow_through_completion_state
                  }</Tag>
                ) : null}
                {signals?.overdueRetentionBreachFollowThroughVerificationState ? (
                  <Tag color="geekblue">verify_state={
                    signals.overdueRetentionBreachFollowThroughVerificationState
                      .overdue_retention_breach_follow_through_verification_state
                  }</Tag>
                ) : null}
                {signals?.overdueRetentionBreachFollowThroughVerificationOutcome ? (
                  <Tag color="red">verify_outcome={
                    signals.overdueRetentionBreachFollowThroughVerificationOutcome
                      .overdue_retention_breach_follow_through_verification_outcome
                  }</Tag>
                ) : null}
                {signals?.overdueAge ? <Tag color="gold">{signals.overdueAge.overdue_age_bucket}</Tag> : null}
                {signals?.overdueTrend ? <Tag color="blue">{signals.overdueTrend.overdue_trend_signal}</Tag> : null}
                {signals?.overdueIntervention ? <Tag color="purple">{signals.overdueIntervention.overdue_intervention_hint}</Tag> : null}
                {signals?.overdueEscalationLane ? <Tag color="volcano">{signals.overdueEscalationLane.overdue_escalation_lane}</Tag> : null}
                {signals?.overdueRecoveryPath ? <Tag color="cyan">{signals.overdueRecoveryPath.overdue_recovery_path}</Tag> : null}
                {signals?.overdueResolutionCheckpoint ? <Tag color="gold">{signals.overdueResolutionCheckpoint.overdue_resolution_checkpoint}</Tag> : null}
                {signals?.overdueResolutionOutcome ? <Tag color="green">{signals.overdueResolutionOutcome.overdue_resolution_outcome}</Tag> : null}
                {signals?.overdueClosureDecision ? <Tag color="orange">{signals.overdueClosureDecision.overdue_closure_decision}</Tag> : null}
                {signals?.overdueArchiveRecommendation ? <Tag color="magenta">{signals.overdueArchiveRecommendation.overdue_archive_recommendation}</Tag> : null}
                {signals?.overdueRetentionGuidance ? <Tag color="lime">{signals.overdueRetentionGuidance.overdue_retention_guidance}</Tag> : null}
                {signals?.overdueRetentionWindow ? <Tag color="geekblue">{signals.overdueRetentionWindow.overdue_retention_window}</Tag> : null}
              </Space>
              <Typography.Text type="secondary">
                pending={scope.pending_count} · reviewed={scope.reviewed_count}
                {scope.latest_reviewed_at ? ` · latest_review=${scope.latest_reviewed_at}` : ""}
              </Typography.Text>
              {Object.keys(scope.pending_by_type).length ? (
                <Typography.Text type="secondary">
                  pending_by_type={JSON.stringify(scope.pending_by_type)}
                </Typography.Text>
              ) : null}
              <ScopeReasonLine label="action_reasons" values={signals?.action?.action_reasons} />
              <ScopeReasonLine label="escalation_reasons" values={signals?.escalation?.escalation_reasons} />
              {signals?.followUp ? (
                <Typography.Text type="secondary">
                  follow_up={signals.followUp.follow_up_window}
                  {signals.followUp.follow_up_due_at ? ` · due_at=${signals.followUp.follow_up_due_at}` : ""}
                </Typography.Text>
              ) : null}
              <ScopeReasonLine label="overdue_reasons" values={signals?.overdue?.follow_up_overdue_reasons} />
              <ScopeReasonLine
                label="overdue_retention_breach_reasons"
                values={signals?.overdueRetentionBreach?.overdue_retention_breach_reasons}
              />
              <ScopeReasonLine
                label="overdue_retention_breach_age_reasons"
                values={signals?.overdueRetentionBreachAge?.overdue_retention_breach_age_reasons}
              />
              <ScopeReasonLine
                label="overdue_retention_breach_action_reasons"
                values={signals?.overdueRetentionBreachAction?.overdue_retention_breach_action_reasons}
              />
              <ScopeReasonLine
                label="overdue_retention_breach_lane_reasons"
                values={signals?.overdueRetentionBreachLane?.overdue_retention_breach_lane_reasons}
              />
              <ScopeReasonLine
                label="overdue_retention_breach_owner_target_reasons"
                values={signals?.overdueRetentionBreachOwnerTarget?.overdue_retention_breach_owner_target_reasons}
              />
              <ScopeReasonLine
                label="overdue_retention_breach_follow_through_mode_reasons"
                values={signals?.overdueRetentionBreachFollowThroughMode?.overdue_retention_breach_follow_through_reasons}
              />
              <ScopeReasonLine
                label="overdue_retention_breach_follow_through_outcome_reasons"
                values={
                  signals?.overdueRetentionBreachFollowThroughOutcome
                    ?.overdue_retention_breach_follow_through_outcome_reasons
                }
              />
              <ScopeReasonLine
                label="overdue_retention_breach_follow_through_completion_reasons"
                values={
                  signals?.overdueRetentionBreachFollowThroughCompletionState
                    ?.overdue_retention_breach_follow_through_completion_reasons
                }
              />
              <ScopeReasonLine
                label="overdue_retention_breach_follow_through_verification_state_reasons"
                values={
                  signals?.overdueRetentionBreachFollowThroughVerificationState
                    ?.overdue_retention_breach_follow_through_verification_reasons
                }
              />
              <ScopeReasonLine
                label="overdue_retention_breach_follow_through_verification_outcome_reasons"
                values={
                  signals?.overdueRetentionBreachFollowThroughVerificationOutcome
                    ?.overdue_retention_breach_follow_through_verification_outcome_reasons
                }
              />
              {signals?.overdueAge ? (
                <Typography.Text type="secondary">
                  overdue_age_days={signals.overdueAge.overdue_age_days ?? "n/a"}
                </Typography.Text>
              ) : null}
              {signals?.overdueType && Object.keys(signals.overdueType.overdue_memory_type_counts).length ? (
                <Typography.Text type="secondary">
                  overdue_types={JSON.stringify(signals.overdueType.overdue_memory_type_counts)}
                </Typography.Text>
              ) : null}
              {signals?.overdueVisibility &&
              Object.keys(signals.overdueVisibility.overdue_memory_visibility_counts).length ? (
                <Typography.Text type="secondary">
                  overdue_visibility={JSON.stringify(signals.overdueVisibility.overdue_memory_visibility_counts)}
                </Typography.Text>
              ) : null}
              <ScopeReasonLine label="overdue_trend" values={signals?.overdueTrend?.overdue_trend_reasons} />
              <ScopeReasonLine
                label="overdue_intervention"
                values={signals?.overdueIntervention?.overdue_intervention_reasons}
              />
              <ScopeReasonLine
                label="overdue_escalation"
                values={signals?.overdueEscalationLane?.overdue_escalation_reasons}
              />
              <ScopeReasonLine
                label="overdue_recovery"
                values={signals?.overdueRecoveryPath?.overdue_recovery_reasons}
              />
              <ScopeReasonLine
                label="overdue_resolution"
                values={signals?.overdueResolutionCheckpoint?.overdue_resolution_reasons}
              />
              <ScopeReasonLine
                label="overdue_outcome"
                values={signals?.overdueResolutionOutcome?.overdue_resolution_outcome_reasons}
              />
              <ScopeReasonLine
                label="overdue_closure"
                values={signals?.overdueClosureDecision?.overdue_closure_reasons}
              />
              <ScopeReasonLine
                label="overdue_archive"
                values={signals?.overdueArchiveRecommendation?.overdue_archive_reasons}
              />
              {signals?.overdueRetentionGuidance ? (
                <Typography.Text type="secondary">
                  retention={signals.overdueRetentionGuidance.overdue_retention_guidance}
                  {signals.overdueRetentionGuidance.overdue_retention_bucket
                    ? ` · bucket=${signals.overdueRetentionGuidance.overdue_retention_bucket}`
                    : ""}
                </Typography.Text>
              ) : null}
              <ScopeReasonLine
                label="overdue_retention"
                values={signals?.overdueRetentionGuidance?.overdue_retention_reasons}
              />
              {signals?.overdueRetentionWindow ? (
                <Typography.Text type="secondary">
                  retention_window={signals.overdueRetentionWindow.overdue_retention_window}
                  {signals.overdueRetentionWindow.overdue_retention_window_due_at
                    ? ` · due_at=${signals.overdueRetentionWindow.overdue_retention_window_due_at}`
                    : ""}
                </Typography.Text>
              ) : null}
              <ScopeReasonLine
                label="overdue_retention_window"
                values={signals?.overdueRetentionWindow?.overdue_retention_window_reasons}
              />
            </Space>
          </List.Item>
        );
      }}
    />
  );
}

function ScopeReasonLine({
  label,
  values,
}: {
  label: string;
  values?: string[];
}) {
  if (!values?.length) {
    return null;
  }
  return <Typography.Text type="secondary">{label}={values.join(" · ")}</Typography.Text>;
}
