import { useEffect, useState } from "react";
import { DEFAULT_TASK_LAUNCH_CONFIG, normalizeTaskLaunchConfig, type TaskLaunchConfig } from "./task-launch-config";

const STORAGE_KEY = "zebra-agent-desktop.task-launch-config";
const TRUSTED_LOCAL_DEFAULT_MIGRATION_KEY = "zebra-agent-desktop.trusted-local-default-v1";

function readConfig(): TaskLaunchConfig {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  const migrated = window.localStorage.getItem(TRUSTED_LOCAL_DEFAULT_MIGRATION_KEY) === "1";
  window.localStorage.setItem(TRUSTED_LOCAL_DEFAULT_MIGRATION_KEY, "1");
  if (!raw) return DEFAULT_TASK_LAUNCH_CONFIG;
  try {
    const config = normalizeTaskLaunchConfig(JSON.parse(raw));
    return !migrated && config.networkProfile === "none"
      ? { ...config, networkProfile: "full-trusted-local" }
      : config;
  } catch {
    return DEFAULT_TASK_LAUNCH_CONFIG;
  }
}

export function useTaskLaunchConfig() {
  const [config, setConfig] = useState<TaskLaunchConfig>(readConfig);
  useEffect(() => window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config)), [config]);
  return {
    config,
    patchConfig: (patch: Partial<TaskLaunchConfig>) => setConfig((current) => ({ ...current, ...patch })),
  };
}
