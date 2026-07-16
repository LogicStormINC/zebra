import { Dropdown, Flex, Input, Popover } from "antd";
import locale from "../../_utils/local";
import type { McpCapabilitiesResponse, McpPromptsResponse } from "../../types";
import { compactWorkspaceLabel, type TaskLaunchConfig } from "../../lib/task-launch-config";
import { McpTaskSelector } from "../McpTaskSelector";
import { McpPromptSelector } from "../McpPromptSelector";
import { useConversationPaneStyle } from "../CodexConversationPane.styles";
import { useTaskLaunchStyle } from "../TaskLaunchConfig.styles";

interface TaskLaunchControlsProps {
  capabilities: McpCapabilitiesResponse | undefined;
  capabilitiesBusy: boolean;
  capabilitiesError: string | null;
  prompts: McpPromptsResponse | undefined;
  promptsBusy: boolean;
  promptsError: string | null;
  config: TaskLaunchConfig;
  effectiveConfig: TaskLaunchConfig;
  editable: boolean;
  onPatch: (patch: Partial<TaskLaunchConfig>) => void;
  onRetryPrompts: () => void;
}

export function TaskLaunchControls({
  capabilities,
  capabilitiesBusy,
  capabilitiesError,
  prompts,
  promptsBusy,
  promptsError,
  config,
  effectiveConfig,
  editable,
  onPatch,
  onRetryPrompts,
}: TaskLaunchControlsProps) {
  const { styles } = useConversationPaneStyle();
  const { styles: launchStyles } = useTaskLaunchStyle();
  const workspaceEditor = (
    <div className={launchStyles.editor}>
      <strong>新任务工作区</strong>
      <Input
        aria-label="新任务工作区"
        name="task-workspace"
        onChange={(event) => onPatch({ workspace: event.target.value })}
        placeholder="绝对路径或 ."
        status={config.workspace.trim() ? undefined : "error"}
        value={config.workspace}
      />
      <span>路径由本地 API 解析；`.` 表示 API 服务当前目录。</span>
    </div>
  );
  const networkEditor = (
    <div className={launchStyles.editor}>
      <strong>允许访问的域名</strong>
      <Input
        aria-label="允许访问的域名"
        onChange={(event) => onPatch({
          networkAllowlist: event.target.value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean),
        })}
        placeholder="docs.example.com, api.example.com"
        value={config.networkAllowlist.join(", ")}
      />
      <span>仅填写裸域名，使用逗号分隔；不接受协议、路径或通配符。</span>
    </div>
  );
  const mcpEditor = (
    <div className={launchStyles.editor}>
      <McpTaskSelector
        capabilities={capabilities}
        busy={capabilitiesBusy}
        className=""
        errorText={capabilitiesError}
        onResourcesChange={(mcpResourceIds) => onPatch({ mcpResourceIds })}
        onToolsChange={(mcpAllowlist) => onPatch({ mcpAllowlist })}
        selectedResources={config.mcpResourceIds}
        selectedTools={config.mcpAllowlist}
      />
      <McpPromptSelector
        arguments={config.mcpPromptArguments}
        busy={promptsBusy}
        data={prompts}
        errorText={promptsError}
        onArgumentsChange={(mcpPromptArguments) => onPatch({ mcpPromptArguments })}
        onRefresh={onRetryPrompts}
        onSelectionChange={(mcpPromptId, mcpPromptSchema) => onPatch({
          mcpPromptId,
          mcpPromptArguments: {},
          mcpPromptSchema,
        })}
        selectedPromptId={config.mcpPromptId}
      />
    </div>
  );

  return (
    <Flex align="center" className={styles.composerTools} gap={8}>
      <span className={styles.modeSegment}>
        <span className={styles.modePill}>{locale.modeAsk}</span>
        <span className={styles.modePillActive}>{locale.modeAct}</span>
      </span>
      {editable ? (
        <Popover content={workspaceEditor} placement="topLeft" trigger="click">
          <button className={styles.toolbarButton} type="button">工作区: {compactWorkspaceLabel(config.workspace)}</button>
        </Popover>
      ) : <span className={launchStyles.staticBadge}>工作区: {compactWorkspaceLabel(effectiveConfig.workspace)}</span>}
      {editable ? (
        <Dropdown menu={{ items: [
          { key: "workspace_write", label: "权限: 工作区写入", onClick: () => onPatch({ policyProfile: "workspace_write" }) },
          { key: "full_access", label: "权限: 完整访问（全部受控工具）", onClick: () => onPatch({ policyProfile: "full_access" }) },
        ] }} trigger={["click"]}>
          <button className={styles.toolbarButton} type="button">
            {config.policyProfile === "full_access" ? "权限: 完整访问" : locale.accessWorkspaceWrite}
          </button>
        </Dropdown>
      ) : <span className={launchStyles.staticBadge}>权限: {effectiveConfig.policyProfile === "full_access" ? "完整访问" : "工作区写入"}</span>}
      {editable ? (
        <Dropdown menu={{ items: [
          { key: "general", label: "能力: 通用工具", onClick: () => onPatch({ toolProfile: "general" }) },
          { key: "coding", label: "能力: 编码工具", onClick: () => onPatch({ toolProfile: "coding" }) },
        ] }} trigger={["click"]}>
          <button className={styles.toolbarButton} type="button">
            {config.toolProfile === "coding" ? "能力: 编码工具" : "能力: 通用工具"}
          </button>
        </Dropdown>
      ) : <span className={launchStyles.staticBadge}>能力: {effectiveConfig.toolProfile === "coding" ? "编码工具" : "通用工具"}</span>}
      {editable ? (
        <Dropdown menu={{ items: [
          { key: "none", label: "网络: 无外部网络", onClick: () => onPatch({ networkProfile: "none", networkAllowlist: [], mcpAllowlist: [], mcpResourceIds: [], mcpPromptId: null, mcpPromptArguments: {}, mcpPromptSchema: null }) },
          { key: "domain-allowlist", label: "网络: 域名白名单", onClick: () => onPatch({ networkProfile: "domain-allowlist", mcpAllowlist: [], mcpResourceIds: [], mcpPromptId: null, mcpPromptArguments: {}, mcpPromptSchema: null }) },
          { key: "mcp-proxy-only", label: "网络: 仅 MCP 代理", onClick: () => onPatch({ networkProfile: "mcp-proxy-only", networkAllowlist: [] }) },
        ] }} trigger={["click"]}>
          <button className={styles.toolbarButton} type="button">网络: {config.networkProfile === "none" ? "无外部网络" : config.networkProfile}</button>
        </Dropdown>
      ) : <span className={launchStyles.staticBadge}>网络: {effectiveConfig.networkProfile}</span>}
      {editable && config.networkProfile === "domain-allowlist" ? (
        <Popover content={networkEditor} placement="topLeft" trigger="click">
          <button className={styles.toolbarButton} type="button">域名: {config.networkAllowlist.length || "未配置"}</button>
        </Popover>
      ) : null}
      {editable && config.networkProfile === "mcp-proxy-only" ? (
        <Popover content={mcpEditor} placement="topLeft" trigger="click">
          <button className={styles.toolbarButton} type="button">MCP: {config.mcpAllowlist.length} 工具 · {config.mcpResourceIds.length} 资源 · {config.mcpPromptId ? 1 : 0} Prompt</button>
        </Popover>
      ) : null}
      <span className={launchStyles.staticBadge}>模型: API 运行时配置</span>
    </Flex>
  );
}
