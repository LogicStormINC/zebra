import assert from "node:assert/strict";
import { optimisticTimelineMessages, projectSessionTimeline, timelinePlanPlacement } from "../src/lib/session-timeline.ts";
import type { SessionEvent } from "../src/types.ts";

const event = (
  sequence: number,
  eventType: string,
  payload: Record<string, unknown> = {},
  eventId = `event-${sequence}`,
): SessionEvent => ({
  event_id: eventId,
  sequence,
  event_type: eventType,
  actor: "harness",
  created_at: `2026-07-17T00:00:${String(sequence).padStart(2, "0")}Z`,
  payload,
});

const timeline = projectSessionTimeline([
  event(1, "model_response_received", null as unknown as Record<string, unknown>),
  event(14, "session_completed"),
  event(2, "user_message_received", { content: "Inspect both files." }),
  event(8, "tool_execution_started", { attempt_number: 1, tool_name: "files.read", tool_call_id: "call-b" }),
  event(4, "tool_call_proposed", { attempt_number: 1, tool_name: "files.read", tool_call_id: "call-a", arguments: { path: "a.txt" } }),
  event(4, "tool_call_proposed", { attempt_number: 1, tool_name: "files.read", tool_call_id: "call-a", arguments: { path: "a.txt" } }, "event-4-replayed"),
  event(6, "tool_call_proposed", { attempt_number: 1, tool_name: "files.read", tool_call_id: "call-b", arguments: { path: "b.txt" } }),
  event(5, "policy_decision_made", { attempt_number: 1, tool_name: "files.read", tool_call_id: "call-a", decision: "allow" }),
  event(7, "policy_decision_made", { attempt_number: 1, tool_name: "files.read", tool_call_id: "call-b", decision: "allow" }),
  event(10, "tool_execution_completed", { attempt_number: 1, tool_name: "files.read", tool_call_id: "call-b", status: "executed", output: "B", metadata: { path: "b.txt" } }),
  event(11, "tool_execution_failed", { attempt_number: 1, tool_name: "files.read", tool_call_id: "call-a", status: "failed", output: "", metadata: { reason: "read_error" } }),
  event(12, "harness_attempt_started", { attempt_number: 2 }),
  event(13, "model_response_received", { attempt_number: 2, assistant_message: "Recovered on retry." }),
  event(13, "model_response_received", { attempt_number: 2, assistant_message: "Recovered on retry." }, "event-13"),
  event(15, "clarification_responded", { content: "Use the safer option." }),
  event(3, "future_internal_event", { hidden_reasoning: "must stay hidden" }),
]);

assert.deepEqual(timeline.map((item) => item.sequence), [2, 4, 6, 12, 13, 14, 15]);
assert.deepEqual(
  timeline.filter((item) => item.kind === "message").map((item) => [item.role, item.content]),
  [["user", "Inspect both files."], ["assistant", "Recovered on retry."], ["user", "Use the safer option."]],
);

assert.deepEqual(optimisticTimelineMessages(timeline, [
  { key: "local-user-1", role: "user", content: "Inspect both files." },
  { key: "event-2", role: "user", content: "Inspect both files." },
  { key: "local-user-2", role: "user", content: "A new optimistic message." },
]), [{ key: "local-user-2", role: "user", content: "A new optimistic message." }]);
assert.deepEqual(optimisticTimelineMessages(timeline, [
  { key: "event-2", role: "user", content: "Inspect both files." },
  { key: "local-user-3", role: "user", content: "Inspect both files." },
]), [{ key: "local-user-3", role: "user", content: "Inspect both files." }]);

const tools = timeline.filter((item) => item.kind === "tool");
assert.equal(tools.length, 2);
assert.deepEqual(tools.map((tool) => [tool.toolCallId, tool.arguments, tool.status, tool.output]), [
  ["call-a", { path: "a.txt" }, "failed", ""],
  ["call-b", { path: "b.txt" }, "completed", "B"],
]);
assert.deepEqual(tools.map((tool) => tool.eventIds.length), [4, 4]);
assert.equal(timeline.some((item) => "hidden_reasoning" in item), false);
assert.equal(timeline.some((item) => item.sequence === 1), false);

const verifierTimeline = projectSessionTimeline([
  event(16, "tests_completed", { summary: "verifier hook skipped", passed: true }),
  event(17, "tests_completed", { summary: "focused tests passed", passed: true }),
]);
assert.deepEqual(
  verifierTimeline.filter((item) => item.kind === "status").map((item) => item.sequence),
  [17],
);

const legacy = projectSessionTimeline([
  event(20, "tool_call_proposed", { attempt_number: 1, tool_name: "files.read", arguments: { path: "first.txt" } }),
  event(21, "tool_call_proposed", { attempt_number: 1, tool_name: "files.read", arguments: { path: "second.txt" } }),
  event(22, "policy_decision_made", { attempt_number: 1, tool_name: "files.read", decision: "allow" }),
  event(23, "policy_decision_made", { attempt_number: 1, tool_name: "files.read", decision: "deny" }),
  event(24, "tool_execution_completed", { attempt_number: 1, tool_name: "files.read", status: "executed", output: "A", metadata: {} }),
  event(25, "tool_execution_completed", { attempt_number: 1, tool_name: "files.read", status: "executed", output: "B", metadata: {} }),
]);

const legacyTools = legacy.filter((item) => item.kind === "tool");
assert.deepEqual(legacyTools.map((tool) => [tool.arguments, tool.policyDecision, tool.status, tool.output]), [
  [{ path: "first.txt" }, "allow", "completed", "A"],
  [{ path: "second.txt" }, "deny", "completed", "B"],
]);
assert.equal(legacyTools.length, 2);
for (const tool of legacyTools) {
  assert.equal("hasPolicy" in tool || "hasStarted" in tool || "hasTerminal" in tool, false);
}

const legacyStarted = projectSessionTimeline([
  event(30, "tool_call_proposed", { attempt_number: 1, tool_name: "files.read", arguments: { path: "a.txt" } }),
  event(31, "tool_call_proposed", { attempt_number: 1, tool_name: "files.read", arguments: { path: "b.txt" } }),
  event(32, "policy_decision_made", { attempt_number: 1, tool_name: "files.read", decision: "deny" }),
  event(33, "tool_execution_started", { attempt_number: 1, tool_name: "files.read" }),
  event(34, "tool_execution_started", { attempt_number: 1, tool_name: "files.read" }),
]).filter((item) => item.kind === "tool");
assert.deepEqual(legacyStarted.map((tool) => [tool.arguments, tool.status]), [
  [{ path: "a.txt" }, "running"],
  [{ path: "b.txt" }, "running"],
]);

const planTimeline = projectSessionTimeline([
  event(40, "user_message_received", { content: "Do it." }),
  event(41, "plan_proposed"),
  event(42, "model_request_started"),
  event(43, "plan_updated"),
]);
assert.deepEqual(timelinePlanPlacement(planTimeline), { mode: "replace", anchorKey: "status:event-43" });
assert.deepEqual(timelinePlanPlacement(projectSessionTimeline([
  event(44, "session_created"),
  event(45, "user_message_received", { content: "Restored task." }),
])), { mode: "after", anchorKey: "message:event-45" });
assert.deepEqual(timelinePlanPlacement(projectSessionTimeline([event(46, "session_created")])), { mode: "start" });

console.log("session timeline checks passed");
