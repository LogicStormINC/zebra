import type { McpPromptCapability, McpPromptsResponse } from "../types";

export type TaskPolicyProfile = "workspace_write" | "full_access";
export type TaskToolProfile = "general" | "coding";
export type TaskNetworkProfile = "none" | "domain-allowlist" | "mcp-proxy-only" | "full-trusted-local";

export interface TaskLaunchConfig {
  workspace: string;
  policyProfile: TaskPolicyProfile;
  toolProfile: TaskToolProfile;
  networkProfile: TaskNetworkProfile;
  networkAllowlist: string[];
  mcpAllowlist: string[];
  mcpResourceIds: string[];
  mcpPromptId: string | null;
  mcpPromptArguments: Record<string, string>;
  mcpPromptSchema: string | null;
}

export const DEFAULT_TASK_LAUNCH_CONFIG: TaskLaunchConfig = {
  workspace: ".",
  policyProfile: "workspace_write",
  toolProfile: "general",
  networkProfile: "full-trusted-local",
  networkAllowlist: [],
  mcpAllowlist: [],
  mcpResourceIds: [],
  mcpPromptId: null,
  mcpPromptArguments: {},
  mcpPromptSchema: null,
};

function normalizedPromptState(candidate: Partial<TaskLaunchConfig>) {
  const promptId = typeof candidate.mcpPromptId === "string" && candidate.mcpPromptId.trim()
    ? candidate.mcpPromptId.trim()
    : null;
  const rawArguments = candidate.mcpPromptArguments;
  const entries = rawArguments && typeof rawArguments === "object" && !Array.isArray(rawArguments)
    ? Object.entries(rawArguments)
    : [];
  const validArguments = entries.length <= 16 && entries.every(([name, value]) => name.trim() && typeof value === "string");
  return {
    mcpPromptId: promptId,
    mcpPromptArguments: promptId && validArguments ? Object.fromEntries(entries.sort(([left], [right]) => left.localeCompare(right))) : {},
    mcpPromptSchema: promptId && typeof candidate.mcpPromptSchema === "string" ? candidate.mcpPromptSchema : null,
  };
}

export function normalizeTaskLaunchConfig(value: unknown): TaskLaunchConfig {
  if (!value || typeof value !== "object") return DEFAULT_TASK_LAUNCH_CONFIG;
  const candidate = value as Partial<TaskLaunchConfig>;
  return {
    workspace: typeof candidate.workspace === "string" ? candidate.workspace : DEFAULT_TASK_LAUNCH_CONFIG.workspace,
    policyProfile: candidate.policyProfile === "full_access" ? "full_access" : "workspace_write",
    toolProfile: candidate.toolProfile === "coding" ? "coding" : "general",
    networkProfile: candidate.networkProfile === "none"
      || candidate.networkProfile === "domain-allowlist"
      || candidate.networkProfile === "mcp-proxy-only"
      || candidate.networkProfile === "full-trusted-local"
      ? candidate.networkProfile
      : DEFAULT_TASK_LAUNCH_CONFIG.networkProfile,
    networkAllowlist: Array.isArray(candidate.networkAllowlist) ? candidate.networkAllowlist.filter((item): item is string => typeof item === "string") : [],
    mcpAllowlist: Array.isArray(candidate.mcpAllowlist) ? candidate.mcpAllowlist.filter((item): item is string => typeof item === "string").sort() : [],
    mcpResourceIds: Array.isArray(candidate.mcpResourceIds) ? candidate.mcpResourceIds.filter((item): item is string => typeof item === "string").sort() : [],
    ...normalizedPromptState(candidate),
  };
}

export function mcpPromptSchema(prompt: McpPromptCapability): string {
  return JSON.stringify(prompt.arguments
    .map(({ name, required }) => ({ name, required }))
    .sort((left, right) => left.name.localeCompare(right.name)));
}

export function reconcileMcpPromptSelection(
  config: TaskLaunchConfig,
  inventory: McpPromptsResponse | undefined,
): Partial<TaskLaunchConfig> | null {
  if (!config.mcpPromptId || !inventory || inventory.status === "unavailable") return null;
  const prompt = inventory.status === "available"
    ? inventory.prompts.find((item) => item.available && item.prompt_id === config.mcpPromptId)
    : undefined;
  if (prompt && config.mcpPromptSchema === mcpPromptSchema(prompt)) return null;
  return { mcpPromptId: null, mcpPromptArguments: {}, mcpPromptSchema: null };
}

export function validateTaskLaunchConfig(
  config: TaskLaunchConfig,
  availableMcpTools?: string[],
  availableMcpResources?: string[],
  availableMcpPrompts?: McpPromptCapability[],
): string | null {
  if (!config.workspace.trim()) return "请先填写任务工作区路径";
  if (!["workspace_write", "full_access"].includes(config.policyProfile)) return "不支持当前权限策略";
  if (!["general", "coding"].includes(config.toolProfile)) return "不支持当前工具配置";
  if (!["none", "domain-allowlist", "mcp-proxy-only", "full-trusted-local"].includes(config.networkProfile)) return "不支持当前网络配置";
  if (config.networkProfile === "domain-allowlist" && config.networkAllowlist.length === 0) return "域名白名单至少需要一个域名";
  if (config.networkProfile !== "domain-allowlist" && config.networkAllowlist.length > 0) return "当前网络配置不接受域名白名单";
  if (config.networkAllowlist.some((item) => !item.trim() || /:\/\/|\/|\*|\s/u.test(item))) return "域名白名单仅接受裸域名";
  if (config.mcpAllowlist.length > 32) return "单个任务最多选择 32 个 MCP 工具";
  if (new Set(config.mcpAllowlist).size !== config.mcpAllowlist.length) return "MCP 工具不能重复选择";
  if (config.mcpAllowlist.length > 0 && config.networkProfile !== "mcp-proxy-only") return "选择 MCP 工具后需要启用仅 MCP 代理网络";
  if (config.mcpAllowlist.some((item) => !/^mcp\.[A-Za-z][A-Za-z0-9_-]{0,31}\.[A-Za-z][A-Za-z0-9_-]{0,31}$/u.test(item))) return "MCP 工具名称无效";
  if (availableMcpTools && config.mcpAllowlist.some((item) => !availableMcpTools.includes(item))) return "已选择的 MCP 工具当前不可用，请重新选择";
  if (config.mcpResourceIds.length > 4) return "单个任务最多选择 4 个 MCP 资源";
  if (new Set(config.mcpResourceIds).size !== config.mcpResourceIds.length) return "MCP 资源不能重复选择";
  if (config.mcpResourceIds.length > 0 && config.networkProfile !== "mcp-proxy-only") return "选择 MCP 资源后需要启用仅 MCP 代理网络";
  if (availableMcpResources && config.mcpResourceIds.some((item) => !availableMcpResources.includes(item))) return "已选择的 MCP 资源当前不可用，请重新选择";
  if (!config.mcpPromptId && Object.keys(config.mcpPromptArguments).length > 0) return "MCP Prompt 参数需要先选择 Prompt";
  if (config.mcpPromptId && config.networkProfile !== "mcp-proxy-only") return "选择 MCP Prompt 后需要启用仅 MCP 代理网络";
  if (config.mcpPromptId) {
    const prompt = availableMcpPrompts?.find((item) => item.available && item.prompt_id === config.mcpPromptId);
    if (availableMcpPrompts && !prompt) return "已选择的 MCP Prompt 当前不可用，请重新选择";
    if (prompt) {
      if (config.mcpPromptSchema !== mcpPromptSchema(prompt)) return "MCP Prompt 参数结构已变化，请重新选择";
      const declared = new Set(prompt.arguments.map((argument) => argument.name));
      const names = Object.keys(config.mcpPromptArguments);
      if (names.length > 16 || names.some((name) => !declared.has(name))) return "MCP Prompt 参数包含未知字段";
      const missing = prompt.arguments.some((argument) => argument.required && !config.mcpPromptArguments[argument.name]?.trim());
      if (missing) return "请填写 MCP Prompt 的必填参数";
    }
    const sizes = Object.values(config.mcpPromptArguments).map((value) => new TextEncoder().encode(value).byteLength);
    if (sizes.some((size) => size > 4 * 1024)) return "单个 MCP Prompt 参数不能超过 4 KiB";
    if (sizes.reduce((total, size) => total + size, 0) > 16 * 1024) return "MCP Prompt 参数总计不能超过 16 KiB";
  }
  return null;
}

export function resolveSessionLaunchConfig(
  configured: TaskLaunchConfig,
  durable: TaskLaunchConfig,
): TaskLaunchConfig {
  return durable.workspace.trim() ? durable : configured;
}

export function compactWorkspaceLabel(workspace: string): string {
  const trimmed = workspace.trim();
  if (!trimmed || trimmed === ".") return trimmed || "未配置";
  if (/^\/+$/u.test(trimmed)) return "/";
  const normalized = trimmed.replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).pop() ?? normalized;
}

export function taskNetworkProfileLabel(profile: TaskNetworkProfile): string {
  if (profile === "none") return "无外部网络";
  if (profile === "domain-allowlist") return "域名白名单";
  if (profile === "mcp-proxy-only") return "仅 MCP 代理";
  return "本地可信网络";
}
