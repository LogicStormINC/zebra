import assert from "node:assert/strict";
import { streamEventsToMessages } from "../src/lib/streaming-messages.ts";
import type { SessionEvent } from "../src/types.ts";

const event = (
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
): SessionEvent => ({
  event_id: `event-${sequence}`,
  sequence,
  event_type: eventType,
  actor: "harness",
  created_at: `2026-07-17T00:00:${String(sequence).padStart(2, "0")}Z`,
  payload,
});

const partial = streamEventsToMessages([
  event(1, "user_message_received", { content: "Stream this." }),
  event(2, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "call-1",
    delta_index: 0,
    content_delta: "Hello ",
  }),
  event(4, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "call-1",
    delta_index: 2,
    content_delta: "!",
  }),
  event(3, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "call-1",
    delta_index: 1,
    content_delta: "Zebra",
  }),
]);
assert.deepEqual(partial.map(({ role, content }) => [role, content]), [
  ["user", "Stream this."],
  ["assistant", "Hello Zebra!"],
]);
assert.equal(partial[1].key, "model-stream:call-1");

const final = streamEventsToMessages([
  event(2, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "call-1",
    delta_index: 0,
    content_delta: "Hello ",
  }),
  event(3, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "call-1",
    delta_index: 1,
    content_delta: "Zebra!",
  }),
  event(4, "model_response_received", {
    attempt_number: 1,
    model_call_id: "call-1",
    assistant_message: "Hello Zebra!",
  }),
]);
assert.deepEqual(final, [{
  key: "event-4",
  role: "assistant",
  status: "success",
  content: "Hello Zebra!",
}]);

console.log("streaming message checks passed");
