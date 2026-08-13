import assert from "node:assert/strict";
import { streamEventsToMessages, type SessionEvent } from "@zebra-agent/task-ui";

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

const recovered = streamEventsToMessages([
  event(1, "user_message_received", { content: "First request" }),
  event(2, "model_request_started", { attempt_number: 1, model_call_id: "cancelled-call" }),
  event(3, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "cancelled-call",
    delta_index: 0,
    content_delta: "Now let me check the repository",
  }),
  event(4, "session_cancelled", {}),
  event(5, "user_message_received", { content: "Retry request" }),
  event(6, "model_request_started", { attempt_number: 1, model_call_id: "failed-call" }),
  event(7, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "failed-call",
    delta_index: 0,
    content_delta: "I will prepare the Markdown file.",
  }),
  event(8, "session_failed", {}),
  event(9, "user_message_received", { content: "Final request" }),
  event(10, "harness_attempt_started", { attempt_number: 1 }),
  event(11, "model_request_started", { attempt_number: 1, model_call_id: "completed-call" }),
  event(12, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "completed-call",
    delta_index: 0,
    content_delta: "Final ",
  }),
  event(13, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "completed-call",
    delta_index: 1,
    content_delta: "report",
  }),
  event(14, "model_response_received", {
    attempt_number: 1,
    model_call_id: "completed-call",
    assistant_message: "Final report",
  }),
  event(15, "session_completed", {}),
]);
assert.deepEqual(recovered.map(({ role, content }) => [role, content]), [
  ["user", "First request"],
  ["user", "Retry request"],
  ["user", "Final request"],
  ["assistant", "Final report"],
]);

const superseded = streamEventsToMessages([
  event(20, "model_response_delta", {
    attempt_number: 1,
    model_call_id: "stale-call",
    delta_index: 0,
    content_delta: "Stale draft",
  }),
  event(21, "model_request_started", { attempt_number: 2, model_call_id: "current-call" }),
  event(22, "model_response_delta", {
    attempt_number: 2,
    model_call_id: "current-call",
    delta_index: 0,
    content_delta: "Current draft",
  }),
]);
assert.deepEqual(superseded.map(({ key, content }) => [key, content]), [
  ["model-stream:current-call", "Current draft"],
]);

console.log("streaming message checks passed");
