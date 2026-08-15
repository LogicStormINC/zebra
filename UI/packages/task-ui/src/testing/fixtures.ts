import type { SessionEvent } from "../core/public-types.ts";

export function makeSessionEvent(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown> = {},
  eventId = `event-${sequence}`,
  created_at = `2026-07-17T00:00:${String(sequence).padStart(2, "0")}Z`,
): SessionEvent {
  return {
    event_id: eventId,
    sequence,
    event_type: eventType,
    actor: "harness",
    created_at,
    payload,
  };
}
