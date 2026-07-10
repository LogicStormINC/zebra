import locale from "./local";
import type { SessionSummary } from "../types";
import { projectWorkspaceLabel } from "../lib/workspace-projection";

export function sessionStatusLabel(status: string | undefined): string {
  if (status === "ready") return locale.statusReady;
  if (status === "running") return locale.statusRunning;
  if (status === "waiting_approval" || status === "waiting_user") return locale.statusWaiting;
  if (status === "completed") return locale.statusDone;
  if (status === "failed") return locale.statusFailed;
  if (["stopped", "cancelled", "canceled"].includes(status ?? "")) return locale.statusStopped;
  if (status === "review") return locale.statusReview;
  return locale.statusDraft;
}

export function sessionWorkspaceLabel(summary: SessionSummary | null | undefined): string {
  return projectWorkspaceLabel(summary?.workspace?.workspace_root, locale.notBound);
}
