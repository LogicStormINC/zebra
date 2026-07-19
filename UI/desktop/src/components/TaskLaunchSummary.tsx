import type { SessionSummary } from "../types";
import { compactWorkspaceLabel, taskNetworkProfileLabel, type TaskLaunchConfig } from "../lib/task-launch-config";

interface TaskLaunchSummaryProps {
  className: string;
  config: TaskLaunchConfig;
  editable: boolean;
  errorText: string | null;
  sessionSummary: SessionSummary | null;
}

export function TaskLaunchSummary({ className, config, editable, errorText, sessionSummary }: TaskLaunchSummaryProps) {
  const capturedPrompt = sessionSummary?.attachments?.find((item) => item.source_type === "mcp_prompt");
  const promptTitle = capturedPrompt
    ? [capturedPrompt.source_server, capturedPrompt.source_id, ...(capturedPrompt.source_argument_names ?? [])].filter(Boolean).join(" · ")
    : undefined;
  return (
    <div className={className} role="status">
      <strong>{editable ? "启动配置" : "会话配置"}</strong>
      <span title={config.workspace}>工作区 · {compactWorkspaceLabel(config.workspace)}</span>
      <span>权限 · {config.policyProfile === "full_access" ? "完整访问" : "工作区写入"}</span>
      <span>能力 · {config.toolProfile === "coding" ? "编码工具" : "通用工具"}</span>
      <span>网络 · {taskNetworkProfileLabel(config.networkProfile)}</span>
      {config.networkProfile === "mcp-proxy-only" ? <span>MCP · {config.mcpAllowlist.length} 工具 · {config.mcpResourceIds.length} 资源{editable ? ` · ${config.mcpPromptId ? 1 : 0} Prompt` : ""}</span> : null}
      {capturedPrompt ? <span title={promptTitle}>Prompt · {capturedPrompt.source_server ?? "MCP"} · {(capturedPrompt.source_argument_names ?? []).length} 参数</span> : null}
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
