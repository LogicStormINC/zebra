export type TaskPolicyProfile = "workspace_write" | "full_access";
export type TaskToolProfile = "general" | "coding";
export type TaskNetworkProfile = "none" | "domain-allowlist" | "mcp-proxy-only";

export interface TaskLaunchConfig {
  workspace: string;
  policyProfile: TaskPolicyProfile;
  toolProfile: TaskToolProfile;
  networkProfile: TaskNetworkProfile;
  networkAllowlist: string[];
}

export const DEFAULT_TASK_LAUNCH_CONFIG: TaskLaunchConfig = {
  workspace: ".",
  policyProfile: "workspace_write",
  toolProfile: "general",
  networkProfile: "none",
  networkAllowlist: [],
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
  };
}

export function validateTaskLaunchConfig(config: TaskLaunchConfig): string | null {
  if (!config.workspace.trim()) return "请先填写任务工作区路径";
  if (!["workspace_write", "full_access"].includes(config.policyProfile)) return "不支持当前权限策略";
  if (!["general", "coding"].includes(config.toolProfile)) return "不支持当前工具配置";
  if (!["none", "domain-allowlist", "mcp-proxy-only"].includes(config.networkProfile)) return "不支持当前网络配置";
  if (config.networkProfile === "domain-allowlist" && config.networkAllowlist.length === 0) return "域名白名单至少需要一个域名";
  if (config.networkProfile !== "domain-allowlist" && config.networkAllowlist.length > 0) return "当前网络配置不接受域名白名单";
  if (config.networkAllowlist.some((item) => !item.trim() || /:\/\/|\/|\*|\s/u.test(item))) return "域名白名单仅接受裸域名";
  return null;
}

export function compactWorkspaceLabel(workspace: string): string {
  const trimmed = workspace.trim();
  if (!trimmed || trimmed === ".") return trimmed || "未配置";
  if (/^\/+$/u.test(trimmed)) return "/";
  const normalized = trimmed.replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).pop() ?? normalized;
}
