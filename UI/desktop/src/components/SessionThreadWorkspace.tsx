import { CheckOutlined } from "@ant-design/icons";
import React from "react";
import locale from "../_utils/local";
import type { ChatMessage } from "../lib/chat-surface";
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
type StageState = "pending" | "active" | "done";
type StageKey = "planning" | "context" | "tools" | "result" | "verification" | "completed" | "review";

const STAGES = [
  { key: "planning", label: locale.stagePlanning },
  { key: "context", label: locale.stageContext },
  { key: "tools", label: locale.stageTools },
  { key: "result", label: locale.stageResult },
  { key: "verification", label: locale.stageVerification },
  { key: "completed", label: locale.stageCompleted },
  { key: "review", label: locale.stageReview },
] as const;

const PLANNING_EVENTS = new Set([
  "session_created",
  "user_message_received",
  "task_prepared",
  "plan_proposed",
  "plan_approved",
  "plan_updated",
  "model_request_started",
  "harness_attempt_started",
]);
const TOOL_EVENTS = new Set(["tool_execution_started", "tool_execution_completed", "tool_execution_failed"]);

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
};

function toolName(event: SessionEvent) {
  return typeof event.payload.tool_name === "string" ? event.payload.tool_name.toLowerCase() : "";
}

function eventStage(event: SessionEvent): StageKey | null {
  if (PLANNING_EVENTS.has(event.event_type)) return "planning";
  if (["approval_requested", "approval_granted", "approval_rejected", "clarification_requested", "clarification_responded"].includes(event.event_type)) return "review";
  if (["session_completed", "session_failed", "session_cancelled"].includes(event.event_type)) return "completed";
  if (["model_response_received", "patch_applied"].includes(event.event_type)) return "result";
  if (event.event_type === "tests_completed") return "verification";
  if (!TOOL_EVENTS.has(event.event_type)) return null;

  const name = toolName(event);
  if (["test", "check", "verify"].some((fragment) => name.includes(fragment))) return "verification";
  if (["read", "search", "list", "glob", "retrieve"].some((fragment) => name.includes(fragment))) return "context";
  return "tools";
}

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
  const populatedStages = STAGES.map((stage) => ({
    ...stage,
    events: events.filter((event) => eventStage(event) === stage.key),
  }));
  const lastPopulatedIndex = populatedStages.reduce((last, stage, index) => stage.events.length ? index : last, -1);
  const terminal = ["completed", "failed", "cancelled", "canceled", "stopped"].includes(sessionSummary?.status ?? "");
  const tabs: Array<{ key: InspectorTab; label: string }> = [
    { key: "context", label: locale.inspectorContext },
    { key: "logs", label: locale.inspectorLogs },
  ];

  const stageState = (index: number, count: number): StageState => {
    if (!count) return "pending";
    if (!terminal && index === lastPopulatedIndex) return "active";
    return "done";
  };

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
          <p>{isDraft ? locale.notStarted : `${events.length} ${locale.eventsRecorded}`}</p>
        </article>
        {hasVisibleTaskPlan(sessionSummary?.task_plan) ? <SessionTaskPlan plan={sessionSummary.task_plan} /> : null}
        <div className={styles.stageList}>
          {populatedStages.map((stage, index) => {
            const state = isDraft ? "pending" : stageState(index, stage.events.length);
            const latest = stage.events[stage.events.length - 1];
            return <div className={`${styles.stage} ${state === "active" ? styles.stageActive : state === "done" ? styles.stageDone : ""}`} key={stage.label}>
              <span className={`${styles.stageDot} ${state === "active" ? styles.stageDotActive : state === "done" ? styles.stageDotDone : ""}`}>
                {state === "done" ? <CheckOutlined /> : index + 1}
              </span>
              <span className={styles.stageText}>
                <strong>{stage.label}</strong>
                <span>{latest ? EVENT_LABELS[latest.event_type] ?? latest.event_type : locale.stagePending}</span>
              </span>
              <span className={styles.stageMeta}>{latest ? formatTime(latest.created_at) : ""}</span>
            </div>;
          })}
        </div>
        {!isDraft ? <>
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
          <SessionExecutionTrace events={events} />
          <div className={styles.messageStack}>{messages.map((message) => message.role === "assistant" ? (
            <AssistantMessageBlock key={message.key} message={message} />
          ) : (
            <div className={styles.userWrap} key={message.key}><div className={styles.userCard}>{message.content}</div></div>
          ))}</div>
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
