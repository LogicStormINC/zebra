import assert from "node:assert/strict";
import { projectRuntimeActivity, runtimeActivityTiming, type SessionEvent } from "@zebra-agent/task-ui";

const event = (sequence: number, eventType: string, payload: Record<string, unknown> = {}): SessionEvent => ({
  event_id: `event-${sequence}`,
  sequence,
  event_type: eventType,
  actor: "harness",
  created_at: `2026-07-17T00:00:${String(sequence).padStart(2, "0")}Z`,
  payload,
});

assert.deepEqual(projectRuntimeActivity(undefined, [], true), {
  title: "正在开始任务",
  detail: "已收到你的请求",
  startedAt: undefined,
  updatedAt: undefined,
});
assert.equal(projectRuntimeActivity("completed", [event(1, "session_completed")], false), null);
assert.deepEqual(projectRuntimeActivity("completed", [event(1, "session_completed")], true), {
  title: "正在开始任务",
  detail: "已收到你的请求",
});
assert.equal(projectRuntimeActivity("waiting_approval", [event(1, "approval_requested")], true), null);
assert.equal(projectRuntimeActivity("waiting_input", [event(1, "clarification_requested")], true), null);
assert.deepEqual(projectRuntimeActivity("running", [
  event(1, "user_message_received", { content: "Search" }),
  event(2, "model_request_started"),
], false), {
  title: "正在生成答复",
  detail: "等待模型返回",
  startedAt: "2026-07-17T00:00:01Z",
  updatedAt: "2026-07-17T00:00:02Z",
});
assert.deepEqual(projectRuntimeActivity("running", [
  event(1, "user_message_received"),
  event(2, "tool_execution_started", { attempt_number: 1, tool_name: "web.search" }),
], false)?.title, "正在搜索网络");
assert.equal(projectRuntimeActivity("running", [event(1, "model_response_received", { assistant_message: "Done" })], true), null);

const timing = runtimeActivityTiming(
  { title: "正在处理任务", detail: "执行已启动", startedAt: "2026-07-17T00:00:00Z", updatedAt: "2026-07-17T00:00:02Z" },
  Date.parse("2026-07-17T00:01:05Z"),
);
assert.deepEqual(timing, { elapsedLabel: "1 分 5 秒", silent: true });

console.log("runtime activity checks passed");
