export type TaskPolicyProfile = "workspace_write" | "full_access";
export type TaskToolProfile = "general" | "coding";

export interface TaskLaunchConfig {
  workspace: string;
  policyProfile: TaskPolicyProfile;
  toolProfile: TaskToolProfile;
}

export const DEFAULT_TASK_LAUNCH_CONFIG: TaskLaunchConfig = {
  workspace: ".",
  policyProfile: "workspace_write",
  toolProfile: "general",
};

export function normalizeTaskLaunchConfig(value: unknown): TaskLaunchConfig {
  if (!value || typeof value !== "object") return DEFAULT_TASK_LAUNCH_CONFIG;
  const candidate = value as Partial<TaskLaunchConfig>;
  return {
    workspace: typeof candidate.workspace === "string" ? candidate.workspace : DEFAULT_TASK_LAUNCH_CONFIG.workspace,
    policyProfile: candidate.policyProfile === "full_access" ? "full_access" : "workspace_write",
    toolProfile: candidate.toolProfile === "coding" ? "coding" : "general",
  };
}

export function validateTaskLaunchConfig(config: TaskLaunchConfig): string | null {
  if (!config.workspace.trim()) return "请先填写任务工作区路径";
  if (!["workspace_write", "full_access"].includes(config.policyProfile)) return "不支持当前权限策略";
  if (!["general", "coding"].includes(config.toolProfile)) return "不支持当前工具配置";
  return null;
}

export function compactWorkspaceLabel(workspace: string): string {
  const trimmed = workspace.trim();
  if (!trimmed || trimmed === ".") return trimmed || "未配置";
  if (/^\/+$/u.test(trimmed)) return "/";
  const normalized = trimmed.replace(/\/+$/, "");
  return normalized.split("/").filter(Boolean).pop() ?? normalized;
}
