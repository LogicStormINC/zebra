import type { SessionHandoffPayload, SessionHandoffResponse } from "../types";

export function isHandoffSafeBoundary(status: string | undefined) {
  return status === "completed" || status === "suspended";
}

export function handoffIdempotencyScope(sessionId: string, payload: SessionHandoffPayload) {
  return `${sessionId}:${JSON.stringify(payload)}`;
}

export function handoffBreadcrumb(result: SessionHandoffResponse) {
  return `${result.source_session_id.slice(0, 8)} → ${result.child_session_id.slice(0, 8)} · handoff ${result.handoff_id.slice(0, 8)}`;
}
