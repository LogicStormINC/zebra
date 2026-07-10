import { useEffect, useMemo, useState } from "react";
import type { ZebraApiClient } from "./zebra-api";
import { formatOperatorError } from "./use-operator-workbench";
import type { MemoryRecord, MemoryScopeKind, ScopeMemoryQueueSummaryResponse } from "../types";

export interface MemoryScopeOption {
  kind: MemoryScopeKind;
  label: string;
  targetId: string;
}

export interface MemoryScopeSurface {
  scope: MemoryScopeOption | null;
  loading: boolean;
  errorText: string | null;
  queueSummary: ScopeMemoryQueueSummaryResponse | null;
  memories: MemoryRecord[];
  refresh: () => Promise<void>;
}

export function buildMemoryScopeOptions(sessionId: string, userId: string, tenantId: string): MemoryScopeOption[] {
  const scopes: MemoryScopeOption[] = [];
  if (sessionId.trim()) {
    scopes.push({ kind: "session", label: "Session", targetId: sessionId.trim() });
  }
  if (userId.trim()) {
    scopes.push({ kind: "user", label: "User", targetId: userId.trim() });
  }
  if (tenantId.trim()) {
    scopes.push({ kind: "tenant", label: "Tenant", targetId: tenantId.trim() });
  }
  return scopes;
}

async function loadScopeSurface(api: ZebraApiClient, scope: MemoryScopeOption) {
  switch (scope.kind) {
    case "session": {
      const [inventory, queueSummary] = await Promise.all([
        api.memory(scope.targetId),
        api.sessionMemoryQueueSummary(scope.targetId),
      ]);
      return {
        queueSummary,
        memories: inventory.memories,
      };
    }
    case "user": {
      const [inventory, queueSummary] = await Promise.all([
        api.userMemory(scope.targetId),
        api.userMemoryQueueSummary(scope.targetId),
      ]);
      return {
        queueSummary,
        memories: inventory.memories,
      };
    }
    case "tenant": {
      const [inventory, queueSummary] = await Promise.all([
        api.tenantMemory(scope.targetId),
        api.tenantMemoryQueueSummary(scope.targetId),
      ]);
      return {
        queueSummary,
        memories: inventory.memories,
      };
    }
  }
}

export function useMemoryScopeSurface(
  api: ZebraApiClient,
  sessionId: string,
  userId: string,
  tenantId: string,
  selectedScope: MemoryScopeKind,
): MemoryScopeSurface {
  const scopes = useMemo(
    () => buildMemoryScopeOptions(sessionId, userId, tenantId),
    [sessionId, userId, tenantId],
  );
  const scope = scopes.find((item) => item.kind === selectedScope) ?? null;
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [queueSummary, setQueueSummary] = useState<ScopeMemoryQueueSummaryResponse | null>(null);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);

  async function refresh() {
    if (!scope) {
      setQueueSummary(null);
      setMemories([]);
      setErrorText(null);
      return;
    }
    setLoading(true);
    setErrorText(null);
    try {
      const surface = await loadScopeSurface(api, scope);
      setQueueSummary(surface.queueSummary);
      setMemories(surface.memories);
    } catch (error) {
      setErrorText(formatOperatorError(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, [scope?.kind, scope?.targetId, api]);

  return {
    scope,
    loading,
    errorText,
    queueSummary,
    memories,
    refresh,
  };
}
