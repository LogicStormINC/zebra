import { useEffect, useState } from "react";
import type { OperatorConfig } from "../types";

const STORAGE_KEY = "zebra-agent-desktop.operator-config";

const DEFAULT_CONFIG: OperatorConfig = {
  apiBaseUrl: "http://127.0.0.1:8000",
  authToken: "",
  sessionId: "",
  userId: "",
  tenantId: "",
};

function readStoredConfig(): OperatorConfig {
  if (typeof window === "undefined") {
    return DEFAULT_CONFIG;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return DEFAULT_CONFIG;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<OperatorConfig>;
    return {
      ...DEFAULT_CONFIG,
      ...parsed,
    };
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function useOperatorConfig() {
  const [config, setConfig] = useState<OperatorConfig>(readStoredConfig);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  }, [config]);

  function patchConfig(patch: Partial<OperatorConfig>) {
    setConfig((current) => ({ ...current, ...patch }));
  }

  return {
    config,
    patchConfig,
    resetConfig() {
      setConfig(DEFAULT_CONFIG);
    },
  };
}
