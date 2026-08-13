import type { SessionEvent } from "./public-types.ts";

export interface RuntimeActivityProjection {
  title: string;
  detail: string;
  startedAt?: string;
  updatedAt?: string;
}

export interface ToolActivityCopy {
  title: string;
  label: string;
}

const TERMINAL_OR_WAITING_EVENTS = new Set([
  "approval_requested",
  "clarification_requested",
  "session_suspended",
  "session_completed",
  "session_failed",
  "session_cancelled",
]);

const TOOL_COPY: Record<string, ToolActivityCopy> = {
  "web.search": { title: "正在搜索网络", label: "网络搜索" },
  "web.fetch": { title: "正在读取网页", label: "网页读取" },
  "files.list": { title: "正在浏览文件", label: "文件浏览" },
  "files.read": { title: "正在读取文件", label: "文件读取" },
  "files.search": { title: "正在搜索文件", label: "文件搜索" },
  "command.run": { title: "正在运行命令", label: "命令执行" },
  "tests.run": { title: "正在运行测试", label: "测试" },
  "git.status": { title: "正在检查工作区", label: "Git 状态" },
};

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function attemptNumber(event: SessionEvent): number | undefined {
  const value = event.payload.attempt_number;
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : undefined;
}

function toolCopy(event: SessionEvent, mapToolLabel: (name: string, fallback: ToolActivityCopy) => ToolActivityCopy) {
  const name = stringValue(event.payload.tool_name);
  return name
    ? mapToolLabel(name, TOOL_COPY[name] ?? { title: "正在使用工具", label: name })
    : { title: "正在使用工具", label: "工具执行" };
}

export function projectRuntimeActivity(
  sessionStatus: string | undefined,
  events: SessionEvent[],
  isRequesting: boolean,
  mapToolLabel: (name: string, fallback: ToolActivityCopy) => ToolActivityCopy = (_name, fallback) => fallback,
): RuntimeActivityProjection | null {
  if (!isRequesting && sessionStatus !== "running") return null;
  if (["waiting_approval", "waiting_input", "suspended"].includes(sessionStatus ?? "")) return null;
  if (!isRequesting && ["completed", "failed", "cancelled"].includes(sessionStatus ?? "")) return null;

  const ordered = [...events].sort((left, right) => left.sequence - right.sequence);
  const latest = ordered[ordered.length - 1];
  if (latest && TERMINAL_OR_WAITING_EVENTS.has(latest.event_type)) {
    if (isRequesting && ["session_completed", "session_failed", "session_cancelled"].includes(latest.event_type)) {
      return { title: "正在开始任务", detail: "已收到你的请求" };
    }
    return null;
  }
  const start = [...ordered].reverse().find((event) => (
    event.event_type === "user_message_received" || event.event_type === "clarification_responded"
  )) ?? ordered[0];
  const base = { startedAt: start?.created_at, updatedAt: latest?.created_at };
  if (!latest) return { ...base, title: "正在开始任务", detail: "已收到你的请求" };

  if (latest.event_type === "model_request_started") return { ...base, title: "正在生成答复", detail: "等待模型返回" };
  if (latest.event_type === "harness_attempt_started") {
    const attempt = attemptNumber(latest);
    return { ...base, title: "正在处理任务", detail: attempt ? `第 ${attempt} 次执行` : "执行已启动" };
  }
  if (latest.event_type === "tool_call_proposed" || latest.event_type === "policy_decision_made") {
    return { ...base, title: "准备使用工具", detail: toolCopy(latest, mapToolLabel).label };
  }
  if (latest.event_type === "tool_execution_started") {
    const copy = toolCopy(latest, mapToolLabel);
    return { ...base, title: copy.title, detail: copy.label };
  }
  if (latest.event_type === "tool_execution_completed") return { ...base, title: "正在整理结果", detail: `${toolCopy(latest, mapToolLabel).label}已完成` };
  if (latest.event_type === "tool_execution_failed") return { ...base, title: "正在处理工具结果", detail: `${toolCopy(latest, mapToolLabel).label}未完成` };
  if (latest.event_type === "plan_proposed" || latest.event_type === "plan_updated") return { ...base, title: "正在更新计划", detail: "任务计划已记录" };
  if (latest.event_type === "approval_granted" || latest.event_type === "clarification_responded" || latest.event_type === "session_resumed") {
    return { ...base, title: "正在继续任务", detail: "已恢复执行" };
  }
  if (latest.event_type === "model_response_received") return null;
  if (["session_created", "user_message_received", "task_prepared"].includes(latest.event_type)) {
    return { ...base, title: "正在准备任务", detail: latest.event_type === "session_created" ? "会话已创建" : "已收到你的请求" };
  }
  return { ...base, title: "正在处理任务", detail: "运行记录已更新" };
}

export function runtimeActivityTiming(
  activity: RuntimeActivityProjection,
  nowMs: number,
  fallbackStartedAtMs = nowMs,
) {
  const parsedStart = activity.startedAt ? Date.parse(activity.startedAt) : Number.NaN;
  const parsedUpdate = activity.updatedAt ? Date.parse(activity.updatedAt) : Number.NaN;
  const startedAtMs = Number.isNaN(parsedStart) ? fallbackStartedAtMs : parsedStart;
  const updatedAtMs = Number.isNaN(parsedUpdate) ? startedAtMs : parsedUpdate;
  const elapsedSeconds = Math.max(0, Math.floor((nowMs - startedAtMs) / 1000));
  return {
    elapsedLabel: elapsedSeconds < 60 ? `${elapsedSeconds} 秒` : `${Math.floor(elapsedSeconds / 60)} 分 ${elapsedSeconds % 60} 秒`,
    silent: nowMs - updatedAtMs >= 8_000,
  };
}
