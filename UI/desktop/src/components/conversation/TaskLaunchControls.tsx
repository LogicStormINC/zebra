import { ControlOutlined, DownOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Dropdown, Flex, Input, Popover, Select } from "antd";
import type { McpCapabilitiesResponse, McpPromptsResponse } from "../../types";
import { compactWorkspaceLabel, taskNetworkProfileLabel, type TaskLaunchConfig } from "../../lib/task-launch-config";
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
  editable,
  onPatch,
  onRetryPrompts,
}: TaskLaunchControlsProps) {
  const { styles } = useConversationPaneStyle();
  const { styles: launchStyles } = useTaskLaunchStyle();

  const resetMcp = {
    mcpAllowlist: [],
    mcpResourceIds: [],
    mcpPromptId: null,
    mcpPromptArguments: {},
    mcpPromptSchema: null,
  };
  const editor = (
    <div className={launchStyles.editor}>
      <div className={styles.launchEditorHeading}>
        <strong>任务配置</strong>
        <span>仅应用于尚未启动的新任务</span>
      </div>
      <label className={styles.launchEditorField}>
        <span>工作区</span>
        <Input
          aria-label="新任务工作区"
          name="task-workspace"
          onChange={(event) => onPatch({ workspace: event.target.value })}
          placeholder="绝对路径或 ."
          status={config.workspace.trim() ? undefined : "error"}
          value={config.workspace}
        />
      </label>
      <div className={styles.launchEditorGrid}>
        <label className={styles.launchEditorField}>
          <span>工具能力</span>
          <Select
            aria-label="工具能力"
            onChange={(toolProfile) => onPatch({ toolProfile })}
            options={[{ value: "general", label: "通用工具" }, { value: "coding", label: "编码工具" }]}
            value={config.toolProfile}
          />
        </label>
        <label className={styles.launchEditorField}>
          <span>网络</span>
          <Select
            aria-label="网络配置"
            onChange={(networkProfile) => onPatch({
              networkProfile,
              networkAllowlist: networkProfile === "domain-allowlist" ? config.networkAllowlist : [],
              ...(networkProfile === "mcp-proxy-only" ? {} : resetMcp),
            })}
            options={[
              { value: "none", label: "无外部网络" },
              { value: "domain-allowlist", label: "域名白名单" },
              { value: "mcp-proxy-only", label: "仅 MCP 代理" },
              { value: "full-trusted-local", label: "本地可信网络" },
            ]}
            value={config.networkProfile}
          />
        </label>
      </div>
      {config.networkProfile === "domain-allowlist" ? (
        <label className={styles.launchEditorField}>
          <span>允许访问的域名</span>
          <Input
            aria-label="允许访问的域名"
            onChange={(event) => onPatch({
              networkAllowlist: event.target.value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean),
            })}
            placeholder="docs.example.com, api.example.com"
            value={config.networkAllowlist.join(", ")}
          />
        </label>
      ) : null}
      {editable && config.networkProfile === "mcp-proxy-only" ? (
        <>
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
        </>
      ) : null}
    </div>
  );
  const permissionButton = (
    <button
      aria-label={editable ? "选择任务权限" : "当前任务权限"}
      className={`${styles.permissionButton} ${config.policyProfile === "full_access" ? styles.permissionButtonFull : ""}`}
      disabled={!editable}
      type="button"
    >
      <SafetyCertificateOutlined />
      <span>{config.policyProfile === "full_access" ? "完全访问" : "工作区写入"}</span>
      {editable ? <DownOutlined /> : null}
    </button>
  );

  return (
    <Flex align="center" className={styles.composerTools} gap={4}>
      {editable ? <Dropdown menu={{ items: [
        { key: "workspace_write", label: "工作区写入", onClick: () => onPatch({ policyProfile: "workspace_write" }) },
        { key: "full_access", label: "完全访问（全部受控工具）", onClick: () => onPatch({ policyProfile: "full_access" }) },
      ] }} trigger={["click"]}>
        {permissionButton}
      </Dropdown> : permissionButton}
      {editable ? <Popover content={editor} placement="topLeft" trigger="click">
        <button
          aria-label={`任务配置：${compactWorkspaceLabel(config.workspace)}，${taskNetworkProfileLabel(config.networkProfile)}`}
          className={styles.launchConfigButton}
          type="button"
        ><ControlOutlined /><span>任务配置</span></button>
      </Popover> : null}
    </Flex>
  );
}
