import type { SessionSummary } from "../types";
import { compactWorkspaceLabel, type TaskLaunchConfig } from "../lib/task-launch-config";

interface TaskLaunchSummaryProps {
  className: string;
  config: TaskLaunchConfig;
  editable: boolean;
  errorText: string | null;
  sessionSummary: SessionSummary | null;
}

export function TaskLaunchSummary({ className, config, editable, errorText, sessionSummary }: TaskLaunchSummaryProps) {
  return (
    <div className={className} role="status">
      <strong>{editable ? "启动配置" : "会话配置"}</strong>
      <span title={config.workspace}>工作区 · {compactWorkspaceLabel(config.workspace)}</span>
      <span>权限 · {config.policyProfile === "full_access" ? "完整访问" : "工作区写入"}</span>
      <span>能力 · {config.toolProfile === "coding" ? "编码工具" : "通用工具"}</span>
      <span>网络 · {config.networkProfile === "none" ? "无外部网络" : config.networkProfile}</span>
      {config.networkProfile === "mcp-proxy-only" ? <span>MCP · {config.mcpAllowlist.length}</span> : null}
      {sessionSummary?.attachments?.length ? (
        <span title={sessionSummary.attachments.map((item) => item.file_name).join(", ")}>
          材料 · {sessionSummary.attachments.length}
        </span>
      ) : null}
      <span>模型 · API 运行时配置</span>
      {errorText ? <em>{errorText}</em> : null}
    </div>
  );
}
