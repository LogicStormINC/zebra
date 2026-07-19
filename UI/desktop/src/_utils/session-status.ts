import locale from "./local";
import type { SessionSummary } from "../types";
import { projectWorkspaceLabel } from "../lib/workspace-projection";

export function sessionStatusLabel(status: string | undefined): string {
  if (status === "ready") return locale.statusReady;
  if (status === "running") return locale.statusRunning;
  if (status === "suspended") return locale.statusSuspended;
  if (status === "waiting_approval" || status === "waiting_user") return locale.statusWaiting;
  if (status === "waiting_input") return locale.statusWaitingInput;
  if (status === "completed") return locale.statusDone;
  if (status === "failed") return locale.statusFailed;
  if (["stopped", "cancelled", "canceled"].includes(status ?? "")) return locale.statusStopped;
  if (status === "review") return locale.statusReview;
  return locale.statusDraft;
}

export function activeSessionStatusLabel(status: string | undefined, isRequesting: boolean): string {
  const terminal = ["completed", "failed", "cancelled", "canceled", "stopped"].includes(status ?? "");
  return isRequesting && !terminal ? locale.statusRunning : sessionStatusLabel(status);
}

export function sessionWorkspaceLabel(summary: SessionSummary | null | undefined): string {
  return projectWorkspaceLabel(summary?.workspace?.workspace_root, locale.notBound);
}
