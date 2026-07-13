export type TaskPolicyProfile = "workspace_write" | "full_access";

export interface TaskLaunchConfig {
  workspace: string;
  policyProfile: TaskPolicyProfile;
}

export const DEFAULT_TASK_LAUNCH_CONFIG: TaskLaunchConfig = {
  workspace: ".",
  policyProfile: "workspace_write",
};

export function normalizeTaskLaunchConfig(value: unknown): TaskLaunchConfig {
  if (!value || typeof value !== "object") return DEFAULT_TASK_LAUNCH_CONFIG;
  const candidate = value as Partial<TaskLaunchConfig>;
  return {
    workspace: typeof candidate.workspace === "string" ? candidate.workspace : DEFAULT_TASK_LAUNCH_CONFIG.workspace,
    policyProfile: candidate.policyProfile === "full_access" ? "full_access" : "workspace_write",
  };
}

export function validateTaskLaunchConfig(config: TaskLaunchConfig): string | null {
  if (!config.workspace.trim()) return "请先填写任务工作区路径";
  if (!["workspace_write", "full_access"].includes(config.policyProfile)) return "不支持当前权限策略";
  return null;
}

export function compactWorkspaceLabel(workspace: string): string {
  const normalized = workspace.trim().replace(/\/+$/, "");
  if (!normalized || normalized === ".") return normalized || "未配置";
  return normalized.split("/").filter(Boolean).pop() ?? normalized;
}
