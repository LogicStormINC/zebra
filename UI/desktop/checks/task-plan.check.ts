import assert from "node:assert/strict";
import { hasVisibleTaskPlan } from "../src/lib/task-plan.ts";

assert.equal(hasVisibleTaskPlan(undefined), false);
assert.equal(hasVisibleTaskPlan({ steps: [], summary: { total: 0, pending: 0, in_progress: 0, completed: 0, cancelled: 0 } }), false);
assert.equal(hasVisibleTaskPlan({
  steps: [{ step_id: "draft", content: "Draft the brief", status: "in_progress" }],
  summary: { total: 1, pending: 0, in_progress: 1, completed: 0, cancelled: 0 },
  updated_at: "2026-07-15T12:00:00+00:00",
}), true);

console.log("task plan checks passed");
