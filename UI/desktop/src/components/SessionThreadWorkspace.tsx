import React from "react";
import locale from "../_utils/local";
import { sessionStatusLabel } from "../_utils/session-status";
import type { ChatMessage } from "../lib/chat-surface";
import { optimisticTimelineMessages, projectSessionTimeline, timelinePlanPlacement, type TimelineMessageItem, type TimelineStatusItem } from "../lib/session-timeline";
import { compactWorkspaceLabel } from "../lib/task-launch-config";
import { hasVisibleTaskPlan } from "../lib/task-plan";
import type { ApprovalSummary, SessionEvent, SessionSummary } from "../types";
import { AssistantMessageBlock } from "./AssistantMessageBlock";
import { SessionExecutionTrace } from "./SessionExecutionTrace";
import { SessionTaskPlan } from "./SessionTaskPlan";
import { SessionApprovalPanel } from "./SessionApprovalPanel";
import { SessionClarificationPanel } from "./SessionClarificationPanel";
import { useSessionThreadWorkspaceStyle } from "./SessionThreadWorkspace.styles";

type InspectorTab = "context" | "logs";

const EVENT_LABELS: Record<string, string> = {
  session_created: "会话已创建",
  user_message_received: "已接收任务",
  task_prepared: "任务已准备",
  plan_proposed: "计划已生成",
  plan_approved: "计划已确认",
  plan_updated: "任务计划已更新",
  model_request_started: "模型开始处理",
  model_response_received: "模型已响应",
  harness_attempt_started: "执行尝试已启动",
  tool_execution_started: "工具开始执行",
  tool_execution_completed: "工具执行完成",
  tool_execution_failed: "工具执行失败",
  patch_applied: "任务结果已更新",
  tests_completed: "结果验证已完成",
  approval_requested: "等待用户确认",
  approval_granted: "用户已确认",
  approval_rejected: "用户已拒绝",
  clarification_requested: "等待补充信息",
  clarification_responded: "已补充信息",
  session_completed: "任务已完成",
  session_failed: "任务执行失败",
  session_cancelled: "任务已停止",
  session_suspended: "任务已暂停",
  session_resumed: "任务已恢复",
};

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

interface SessionThreadWorkspaceProps {
  activeLabel: string;
  activeApproval: ApprovalSummary | undefined;
  approvalBusy: boolean;
  approvalErrorText: string | null;
  clarificationBusy: boolean;
  events: SessionEvent[];
  isDraft: boolean;
  messages: ChatMessage[];
  onApprove: (approval: ApprovalSummary) => Promise<unknown>;
  onRespondClarification: (clarificationId: string, content: string) => Promise<unknown>;
  onReject: (approval: ApprovalSummary) => Promise<unknown>;
  sessionSummary: SessionSummary | null;
}

export function SessionThreadWorkspace({
  activeLabel,
  activeApproval,
  approvalBusy,
  approvalErrorText,
  clarificationBusy,
  events,
  isDraft,
  messages,
  onApprove,
  onRespondClarification,
  onReject,
  sessionSummary,
}: SessionThreadWorkspaceProps) {
  const { styles } = useSessionThreadWorkspaceStyle();
  const [inspectorTab, setInspectorTab] = React.useState<InspectorTab>("context");
  const workspaceRoot = sessionSummary?.workspace?.workspace_root;
  const projectLabel = workspaceRoot ? compactWorkspaceLabel(workspaceRoot) : locale.unboundProject;
  const attachments = sessionSummary?.attachments ?? [];
  const mcpResourceCount = attachments.filter((attachment) => attachment.source_type === "mcp_resource").length;
  const capturedPrompt = attachments.find((attachment) => attachment.source_type === "mcp_prompt");
  const promptLabel = capturedPrompt
    ? `${capturedPrompt.source_server ?? "MCP"} · ${(capturedPrompt.source_argument_names ?? []).length} 参数`
    : "未使用";
  const timelineItems = projectSessionTimeline(events);
  const optimisticMessages = optimisticTimelineMessages(timelineItems, messages);
  const visiblePlan = hasVisibleTaskPlan(sessionSummary?.task_plan) ? sessionSummary.task_plan : undefined;
  const planPlacement = visiblePlan ? timelinePlanPlacement(timelineItems) : undefined;
  const planNode = visiblePlan && planPlacement
    ? <SessionTaskPlan key={`plan:${planPlacement.mode === "start" ? "start" : planPlacement.anchorKey}`} plan={visiblePlan} />
    : null;
  const toolCount = timelineItems.filter((item) => item.kind === "tool").length;
  const statusLabel = isDraft
    ? locale.statusDraft
    : sessionSummary ? sessionStatusLabel(sessionSummary.status) : "状态同步中";
  const tabs: Array<{ key: InspectorTab; label: string }> = [
    { key: "context", label: locale.inspectorContext },
    { key: "logs", label: locale.inspectorLogs },
  ];

  const renderMessage = (item: TimelineMessageItem | ChatMessage, key: string) => item.role === "assistant" ? (
    <AssistantMessageBlock key={key} message={item} />
  ) : (
    <div className={styles.userWrap} key={key}><div className={styles.userCard}>{item.content}</div></div>
  );
  const renderStatus = (item: TimelineStatusItem) => (
    <div className={styles.statusRow} key={item.key}>
      <span className={styles.statusMarker} />
      <span>{EVENT_LABELS[item.eventType] ?? item.eventType}</span>
      <span>{item.attemptNumber ? `attempt ${item.attemptNumber} · ` : ""}{formatTime(item.createdAt)}</span>
    </div>
  );

  const renderInspector = () => {
    if (isDraft) return <p className={styles.empty}>{locale.inspectorEmpty}</p>;
    if (inspectorTab === "context") {
      return <div className={styles.inspectorList}>
        <div className={styles.inspectorRow}><span>{locale.project}</span><span title={workspaceRoot ?? locale.workspaceUnbound}>{projectLabel}</span></div>
        <div className={styles.inspectorRow}><span>{locale.workspace}</span><span title={workspaceRoot ?? locale.workspaceUnbound}>{workspaceRoot ? compactWorkspaceLabel(workspaceRoot) : locale.notBound}</span></div>
        <div className={styles.inspectorRow}><span>{locale.policy}</span><span>{sessionSummary?.workspace?.policy_profile ?? locale.notBound}</span></div>
        <div className={styles.inspectorRow}><span>工具配置</span><span>{sessionSummary?.workspace?.tool_profile ?? locale.notBound}</span></div>
        <div className={styles.inspectorRow}><span>网络配置</span><span>{sessionSummary?.workspace?.network_profile ?? "none"}</span></div>
        <div className={styles.inspectorRow}><span>MCP</span><span>{sessionSummary?.workspace?.mcp_allowlist?.length ?? 0} 工具 · {mcpResourceCount} 资源</span></div>
        <div className={styles.inspectorRow}><span>Prompt</span><span>{promptLabel}</span></div>
        <div className={styles.inspectorRow}><span>材料</span><span>{attachments.length}</span></div>
        <div className={styles.inspectorRow}><span>模型</span><span>API 运行时配置</span></div>
        <div className={styles.inspectorRow}><span>{locale.attempt}</span><span>{sessionSummary?.workspace?.last_attempt_number ?? 0}</span></div>
        <div className={styles.inspectorRow}><span>{locale.sequence}</span><span>{sessionSummary?.current_sequence ?? events.length}</span></div>
      </div>;
    }
    const logs = events.slice(-5).reverse();
    return logs.length ? <div className={styles.inspectorList}>{logs.map((event) => (
      <div className={styles.logRow} key={event.event_id}>
        <span>{EVENT_LABELS[event.event_type] ?? event.event_type}</span>
        <span>#{event.sequence} · {formatTime(event.created_at)}</span>
      </div>
    ))}</div> : <p className={styles.empty}>{locale.noLogsYet}</p>;
  };

  return (
    <div className={styles.workspace}>
      <section className={styles.timeline}>
        <article className={styles.taskCard}>
          <div className={styles.eyebrow}>{isDraft ? locale.threadDraft : locale.threadTimeline}</div>
          <h2>{activeLabel}</h2>
          <p>
            <span aria-live="polite" className={styles.currentStatus}>{statusLabel}</span>
            <span aria-hidden="true"> · </span>
            {isDraft ? locale.notStarted : `${events.length} ${locale.eventsRecorded} · ${toolCount} tools`}
          </p>
        </article>
        {!isDraft ? <>
          <div className={styles.eventStream}>
            {planPlacement?.mode === "start" ? planNode : null}
            {timelineItems.map((item) => {
              const isPlanEvent = item.kind === "status" && (item.eventType === "plan_proposed" || item.eventType === "plan_updated");
              if (isPlanEvent) {
                return planPlacement?.mode === "replace" && planPlacement.anchorKey === item.key ? planNode : null;
              }
              const content = item.kind === "message"
                ? renderMessage(item, item.key)
                : item.kind === "tool" ? <SessionExecutionTrace key={item.key} tool={item} /> : renderStatus(item);
              const insertPlanAfter = visiblePlan && planPlacement?.mode === "after" && planPlacement.anchorKey === item.key;
              return <React.Fragment key={`stream:${item.key}`}>
                {content}
                {insertPlanAfter ? planNode : null}
              </React.Fragment>;
            })}
            {optimisticMessages.map((message) => renderMessage(message, message.key))}
          </div>
          <SessionClarificationPanel
            busy={clarificationBusy}
            clarification={sessionSummary?.clarification_context}
            onRespond={onRespondClarification}
          />
          <SessionApprovalPanel
            approval={activeApproval}
            busy={approvalBusy}
            errorText={approvalErrorText}
            onApprove={onApprove}
            onReject={onReject}
          />
        </> : null}
      </section>
      <aside className={styles.inspector}>
        <div className={styles.inspectorTabs} role="tablist">{tabs.map((tab) => (
          <button
            aria-selected={inspectorTab === tab.key}
            className={`${styles.inspectorTab} ${inspectorTab === tab.key ? styles.inspectorTabActive : ""}`}
            key={tab.key}
            onClick={() => setInspectorTab(tab.key)}
            role="tab"
            type="button"
          >
            {tab.label}
          </button>
        ))}</div>
        <div className={styles.inspectorBody} role="tabpanel"><h3>{tabs.find((tab) => tab.key === inspectorTab)?.label}</h3>{renderInspector()}</div>
      </aside>
    </div>
  );
}
