import { Alert } from "antd";

interface MemoryGovernanceAlertsProps {
  actionReasons: string[];
  pressureReasons: string[];
  followUpReasons: string[];
  overdueReasons: string[];
  overdueRetentionBreachReasons: string[];
  overdueRetentionBreachAgeReasons: string[];
  overdueRetentionBreachActionReasons: string[];
  overdueRetentionBreachLaneReasons: string[];
  overdueRetentionBreachOwnerTargetReasons: string[];
  overdueRetentionBreachFollowThroughModeReasons: string[];
  overdueRetentionBreachFollowThroughOutcomeReasons: string[];
  overdueRetentionBreachCompletionStateReasons: string[];
  overdueRetentionBreachVerificationStateReasons: string[];
  overdueRetentionBreachVerificationOutcomeReasons: string[];
  overdueAgeReasons: string[];
  overdueTrendReasons: string[];
  overdueInterventionReasons: string[];
  overdueEscalationReasons: string[];
  overdueRecoveryReasons: string[];
  overdueResolutionReasons: string[];
  overdueOutcomeReasons: string[];
  overdueClosureReasons: string[];
  overdueArchiveReasons: string[];
  overdueRetentionReasons: string[];
  overdueRetentionWindowReasons: string[];
}

export function MemoryGovernanceAlerts(props: MemoryGovernanceAlertsProps) {
  return (
    <>
      <SignalAlert type="info" title="Highest-priority action reasons" reasons={props.actionReasons} />
      <SignalAlert type="warning" title="Highest-pressure scope reasons" reasons={props.pressureReasons} />
      <SignalAlert type="info" title="Highest-priority follow-up reasons" reasons={props.followUpReasons} />
      <SignalAlert type="error" title="Highest-priority overdue reasons" reasons={props.overdueReasons} />
      <SignalAlert type="error" title="Highest-priority overdue breach reasons" reasons={props.overdueRetentionBreachReasons} />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach age reasons"
        reasons={props.overdueRetentionBreachAgeReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach action reasons"
        reasons={props.overdueRetentionBreachActionReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach lane reasons"
        reasons={props.overdueRetentionBreachLaneReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach owner-target reasons"
        reasons={props.overdueRetentionBreachOwnerTargetReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach follow-through mode reasons"
        reasons={props.overdueRetentionBreachFollowThroughModeReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach follow-through outcome reasons"
        reasons={props.overdueRetentionBreachFollowThroughOutcomeReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach follow-through completion-state reasons"
        reasons={props.overdueRetentionBreachCompletionStateReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach follow-through verification-state reasons"
        reasons={props.overdueRetentionBreachVerificationStateReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue breach follow-through verification-outcome reasons"
        reasons={props.overdueRetentionBreachVerificationOutcomeReasons}
      />
      <SignalAlert type="warning" title="Highest-priority overdue age reasons" reasons={props.overdueAgeReasons} />
      <SignalAlert type="info" title="Highest-priority overdue trend reasons" reasons={props.overdueTrendReasons} />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue intervention reasons"
        reasons={props.overdueInterventionReasons}
      />
      <SignalAlert
        type="warning"
        title="Highest-priority overdue escalation reasons"
        reasons={props.overdueEscalationReasons}
      />
      <SignalAlert type="info" title="Highest-priority overdue recovery reasons" reasons={props.overdueRecoveryReasons} />
      <SignalAlert
        type="info"
        title="Highest-priority overdue resolution reasons"
        reasons={props.overdueResolutionReasons}
      />
      <SignalAlert type="success" title="Highest-priority overdue outcome reasons" reasons={props.overdueOutcomeReasons} />
      <SignalAlert type="warning" title="Highest-priority overdue closure reasons" reasons={props.overdueClosureReasons} />
      <SignalAlert type="info" title="Highest-priority overdue archive reasons" reasons={props.overdueArchiveReasons} />
      <SignalAlert type="info" title="Highest-priority overdue retention reasons" reasons={props.overdueRetentionReasons} />
      <SignalAlert
        type="info"
        title="Highest-priority overdue retention window reasons"
        reasons={props.overdueRetentionWindowReasons}
      />
    </>
  );
}

function SignalAlert({
  type,
  title,
  reasons,
}: {
  type: "success" | "info" | "warning" | "error";
  title: string;
  reasons: string[];
}) {
  if (!reasons.length) {
    return null;
  }
  return <Alert type={type} showIcon message={title} description={reasons.join(" · ")} />;
}
