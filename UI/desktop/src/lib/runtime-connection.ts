export type RuntimeConnectionStatus = "checking" | "connected" | "disconnected";

export function projectRuntimeConnection(
  healthStatus: string | undefined,
  healthService: string | undefined,
  isFetching: boolean,
  hasError = false,
): RuntimeConnectionStatus {
  if (hasError) return "disconnected";
  if (healthStatus === "ok" && healthService === "zebra-agent-api") return "connected";
  return isFetching ? "checking" : "disconnected";
}
