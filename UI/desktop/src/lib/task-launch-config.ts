export type TaskPolicyProfile = "workspace_write" | "full_access";
export type TaskToolProfile = "general" | "coding";
export type TaskNetworkProfile = "none" | "domain-allowlist" | "mcp-proxy-only";

export interface TaskLaunchConfig {
  workspace: string;
  policyProfile: TaskPolicyProfile;
  toolProfile: TaskToolProfile;
  networkProfile: TaskNetworkProfile;
  networkAllowlist: string[];
  mcpAllowlist: string[];
}

export const DEFAULT_TASK_LAUNCH_CONFIG: TaskLaunchConfig = {
  workspace: ".",
  policyProfile: "workspace_write",
  toolProfile: "general",
  networkProfile: "none",
  networkAllowlist: [],
  mcpAllowlist: [],
};

export function normalizeTaskLaunchConfig(value: unknown): TaskLaunchConfig {
  if (!value || typeof value !== "object") return DEFAULT_TASK_LAUNCH_CONFIG;
  const candidate = value as Partial<TaskLaunchConfig>;
  return {
    workspace: typeof candidate.workspace === "string" ? candidate.workspace : DEFAULT_TASK_LAUNCH_CONFIG.workspace,
    policyProfile: candidate.policyProfile === "full_access" ? "full_access" : "workspace_write",
    toolProfile: candidate.toolProfile === "coding" ? "coding" : "general",
    networkProfile: candidate.networkProfile === "domain-allowlist" || candidate.networkProfile === "mcp-proxy-only" ? candidate.networkProfile : "none",
    networkAllowlist: Array.isArray(candidate.networkAllowlist) ? candidate.networkAllowlist.filter((item): item is string => typeof item === "string") : [],
    mcpAllowlist: Array.isArray(candidate.mcpAllowlist) ? candidate.mcpAllowlist.filter((item): item is string => typeof item === "string").sort() : [],
  };
}

export function validateTaskLaunchConfig(
  config: TaskLaunchConfig,
  availableMcpTools?: string[],
): string | null {
  if (!config.workspace.trim()) return "请先填写任务工作区路径";
  if (!["workspace_write", "full_access"].includes(config.policyProfile)) return "不支持当前权限策略";
  if (!["general", "coding"].includes(config.toolProfile)) return "不支持当前工具配置";
  if (!["none", "domain-allowlist", "mcp-proxy-only"].includes(config.networkProfile)) return "不支持当前网络配置";
  if (config.networkProfile === "domain-allowlist" && config.networkAllowlist.length === 0) return "域名白名单至少需要一个域名";
  if (config.networkProfile !== "domain-allowlist" && config.networkAllowlist.length > 0) return "当前网络配置不接受域名白名单";
  if (config.networkAllowlist.some((item) => !item.trim() || /:\/\/|\/|\*|\s/u.test(item))) return "域名白名单仅接受裸域名";
  if (config.mcpAllowlist.length > 32) return "单个任务最多选择 32 个 MCP 工具";
  if (new Set(config.mcpAllowlist).size !== config.mcpAllowlist.length) return "MCP 工具不能重复选择";
  if (config.mcpAllowlist.length > 0 && config.networkProfile !== "mcp-proxy-only") return "选择 MCP 工具后需要启用仅 MCP 代理网络";
  if (config.mcpAllowlist.some((item) => !/^mcp\.[A-Za-z][A-Za-z0-9_-]{0,31}\.[A-Za-z][A-Za-z0-9_-]{0,31}$/u.test(item))) return "MCP 工具名称无效";
  if (availableMcpTools && config.mcpAllowlist.some((item) => !availableMcpTools.includes(item))) return "已选择的 MCP 工具当前不可用，请重新选择";
  return null;
}

export function compactWorkspaceLabel(workspace: string): string {
  const trimmed = workspace.trim();
  if (!trimmed || trimmed === ".") return trimmed || "未配置";
  if (/^\/+$/u.test(trimmed)) return "/";
  const normalized = trimmed.replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).pop() ?? normalized;
}
