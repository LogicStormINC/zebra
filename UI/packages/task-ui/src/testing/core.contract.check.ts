import assert from "node:assert/strict";
import { decideActiveApproval } from "../core/approval.ts";
import { buildClarificationResponsePayload } from "../core/clarification.ts";
import { streamEventsToMessages } from "../core/event-reducer.ts";
import { projectRuntimeActivity } from "../core/runtime-activity.ts";
import { hasVisibleTaskPlan } from "../core/task-plan.ts";
import { defaultTurnDisclosure, isTurnCollapsedByDefault } from "../core/turn-disclosure.ts";
import { projectSessionTimeline, timelinePlanPlacement } from "../core/timeline-projector.ts";
import { makeSessionEvent } from "./fixtures.ts";

// W45-P4-01: turn disclosure defaults are deterministic per terminal/running
// status: running open, succeeded collapsed, waiting/failed/canceled open.
assert.equal(defaultTurnDisclosure("running"), "open");
assert.equal(defaultTurnDisclosure("succeeded"), "collapsed");
assert.equal(defaultTurnDisclosure("waiting_user"), "open");
assert.equal(defaultTurnDisclosure("failed"), "open");
assert.equal(defaultTurnDisclosure("canceled"), "open");
assert.equal(defaultTurnDisclosure("cancelled"), "open");
assert.equal(isTurnCollapsedByDefault("succeeded"), true);
assert.equal(isTurnCollapsedByDefault("running"), false);
assert.equal(isTurnCollapsedByDefault("waiting_approval"), false);

// Streaming merge: out-of-order deltas assemble in delta_index order and the
// final replaces the partial in place.
const merged = streamEventsToMessages([
  makeSessionEvent(1, "user_message_received", { content: "Stream this." }),
  makeSessionEvent(2, "model_response_delta", {
    model_call_id: "call-1",
    delta_index: 0,
    content_delta: "Hello ",
  }),
  makeSessionEvent(4, "model_response_delta", {
    model_call_id: "call-1",
    delta_index: 2,
    content_delta: "!",
  }),
  makeSessionEvent(3, "model_response_delta", {
    model_call_id: "call-1",
    delta_index: 1,
    content_delta: "Zebra",
  }),
]);
assert.deepEqual(merged.map(({ role, content }) => [role, content]), [
  ["user", "Stream this."],
  ["assistant", "Hello Zebra!"],
]);
const final = streamEventsToMessages([
  makeSessionEvent(2, "model_response_delta", {
    model_call_id: "call-1",
    delta_index: 0,
    content_delta: "Hello Zebra!",
  }),
  makeSessionEvent(3, "model_response_received", {
    model_call_id: "call-1",
    assistant_message: "Hello Zebra!",
  }),
]);
assert.deepEqual(final, [{
  key: "event-3",
  role: "assistant",
  status: "success",
  content: "Hello Zebra!",
}]);

// W45-P4-02: a real failed/cancelled interruption preserves the merged
// partial answer as an error message (sorted, out-of-order deltas merged).
// It never becomes a canonical final (key stays model-stream:<call>).
const interrupted = streamEventsToMessages([
  makeSessionEvent(1, "user_message_received", { content: "Stream this." }),
  makeSessionEvent(2, "model_response_delta", {
    model_call_id: "call-x",
    delta_index: 0,
    content_delta: "Hello ",
  }),
  makeSessionEvent(4, "model_response_delta", {
    model_call_id: "call-x",
    delta_index: 2,
    content_delta: "!",
  }),
  makeSessionEvent(3, "model_response_delta", {
    model_call_id: "call-x",
    delta_index: 1,
    content_delta: "Zebra",
  }),
  makeSessionEvent(5, "session_failed", {}),
]);
assert.deepEqual(interrupted, [
  { key: "event-1", role: "user", status: "success", content: "Stream this." },
  { key: "model-stream:call-x", role: "assistant", status: "error", content: "Hello Zebra!" },
]);

const cancelled = streamEventsToMessages([
  makeSessionEvent(1, "model_response_delta", {
    model_call_id: "call-y",
    delta_index: 0,
    content_delta: "Partial",
  }),
  makeSessionEvent(2, "session_cancelled", {}),
]);
assert.deepEqual(cancelled, [
  { key: "model-stream:call-y", role: "assistant", status: "error", content: "Partial" },
]);

// No deltas before the interruption -> nothing preserved.
assert.deepEqual(streamEventsToMessages([
  makeSessionEvent(1, "model_request_started", { model_call_id: "call-z" }),
  makeSessionEvent(2, "session_failed", {}),
]), []);

// Existing reset semantics stay pinned: normal completion, approval,
// clarification, and a fresh model request discard uncommitted partials.
assert.deepEqual(streamEventsToMessages([
  makeSessionEvent(1, "model_response_delta", {
    model_call_id: "call-w",
    delta_index: 0,
    content_delta: "draft",
  }),
  makeSessionEvent(2, "session_completed", {}),
]), []);
assert.deepEqual(streamEventsToMessages([
  makeSessionEvent(1, "model_response_delta", {
    model_call_id: "call-a1",
    delta_index: 0,
    content_delta: "draft",
  }),
  makeSessionEvent(2, "approval_requested", {}),
]), []);
assert.deepEqual(streamEventsToMessages([
  makeSessionEvent(1, "model_response_delta", {
    model_call_id: "call-c1",
    delta_index: 0,
    content_delta: "draft",
  }),
  makeSessionEvent(2, "clarification_requested", {}),
]), []);
const superseded = streamEventsToMessages([
  makeSessionEvent(1, "model_response_delta", {
    model_call_id: "stale",
    delta_index: 0,
    content_delta: "Stale",
  }),
  makeSessionEvent(2, "model_request_started", { model_call_id: "fresh" }),
  makeSessionEvent(3, "model_response_delta", {
    model_call_id: "fresh",
    delta_index: 0,
    content_delta: "Fresh",
  }),
]);
assert.deepEqual(superseded.map(({ key, content }) => [key, content]), [
  ["model-stream:fresh", "Fresh"],
]);

// W45-GATE-A-01: a tool-call round discards provisional streamed text; the
// partial never survives as a message (the durable log keeps deltas for
// replay, but the reducer must not surface them as final content).
const toolRound = streamEventsToMessages([
  makeSessionEvent(1, "user_message_received", { content: "Read the file." }),
  makeSessionEvent(2, "model_response_delta", {
    model_call_id: "call-tool",
    delta_index: 0,
    content_delta: "Let me check the repo first...",
  }),
  makeSessionEvent(3, "tool_call_proposed", {
    attempt_number: 1,
    tool_name: "files.read",
    tool_call_id: "call-a",
  }),
  makeSessionEvent(4, "model_response_received", {
    model_call_id: "call-tool",
    assistant_message: "I will read the file.",
  }),
]);
assert.deepEqual(toolRound, [
  { key: "event-1", role: "user", status: "success", content: "Read the file." },
  { key: "event-4", role: "assistant", status: "success", content: "I will read the file." },
]);

// Timeline: duplicate event ids collapse, tool lifecycle folds into one item.
const timeline = projectSessionTimeline([
  makeSessionEvent(1, "user_message_received", { content: "Inspect." }),
  makeSessionEvent(2, "tool_call_proposed", {
    attempt_number: 1,
    tool_name: "files.read",
    tool_call_id: "call-a",
    arguments: { path: "a.txt" },
  }),
  makeSessionEvent(2, "tool_call_proposed", {
    attempt_number: 1,
    tool_name: "files.read",
    tool_call_id: "call-a",
    arguments: { path: "a.txt" },
  }, "event-2-replayed"),
  makeSessionEvent(3, "policy_decision_made", {
    attempt_number: 1,
    tool_name: "files.read",
    tool_call_id: "call-a",
    decision: "allow",
  }),
  makeSessionEvent(4, "tool_execution_completed", {
    attempt_number: 1,
    tool_name: "files.read",
    tool_call_id: "call-a",
    status: "executed",
    output: "A",
  }),
]);
assert.deepEqual(
  timeline.filter((item) => item.kind === "tool").map((item) => [item.kind, item.toolName, item.status]),
  [["tool", "files.read", "completed"]],
);
assert.equal(timeline.filter((item) => item.kind === "message").length, 1);
assert.deepEqual(timelinePlanPlacement(timeline), { mode: "after", anchorKey: "message:event-1" });

// Activity: waiting states produce no projection; completed is null when idle.
assert.equal(projectRuntimeActivity("waiting_approval", [makeSessionEvent(1, "approval_requested")], true), null);
assert.equal(projectRuntimeActivity("completed", [makeSessionEvent(1, "session_completed")], false), null);
assert.equal(projectRuntimeActivity(undefined, [], true)?.title, "正在开始任务");

// Plan / clarification / approval primitives.
assert.equal(hasVisibleTaskPlan(undefined), false);
assert.equal(hasVisibleTaskPlan({
  steps: [{ step_id: "draft", content: "Draft", status: "in_progress" }],
  summary: { total: 1, pending: 0, in_progress: 1, completed: 0, cancelled: 0 },
}), true);
assert.deepEqual(buildClarificationResponsePayload(" clar-1 ", " use b "), {
  clarification_id: "clar-1",
  content: "use b",
});
assert.throws(() => buildClarificationResponsePayload("", "x"), /required/);

const calls: string[] = [];
const api = {
  approve: async () => { calls.push("approve"); return {}; },
  reject: async () => { calls.push("reject"); return {}; },
  resume: async () => { calls.push("resume"); return {}; },
};
await decideActiveApproval(api, { approval_id: "approval-1", session_id: "session-1" }, "approve");
assert.deepEqual(calls, ["approve", "resume"]);
await decideActiveApproval(api, { approval_id: "approval-1", session_id: "session-1" }, "reject");
assert.deepEqual(calls, ["approve", "resume", "reject"]);

console.log("task-ui core contract checks passed");
