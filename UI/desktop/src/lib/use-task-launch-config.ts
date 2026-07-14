import { useEffect, useState } from "react";
import { DEFAULT_TASK_LAUNCH_CONFIG, normalizeTaskLaunchConfig, type TaskLaunchConfig } from "./task-launch-config";

const STORAGE_KEY = "zebra-agent-desktop.task-launch-config";

function readConfig(): TaskLaunchConfig {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return DEFAULT_TASK_LAUNCH_CONFIG;
  try {
    return normalizeTaskLaunchConfig(JSON.parse(raw));
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
