import assert from "node:assert/strict";
import {
  handoffBreadcrumb,
  handoffIdempotencyScope,
  isHandoffSafeBoundary,
} from "../src/lib/session-handoff.ts";

assert.equal(isHandoffSafeBoundary("completed"), true);
assert.equal(isHandoffSafeBoundary("suspended"), true);
assert.equal(isHandoffSafeBoundary("running"), false);

const payload = {
  title: "Stage two",
  objective: "Continue",
  stage_prompt: "Implement the next phase",
};
assert.equal(
  handoffIdempotencyScope("parent", payload),
  handoffIdempotencyScope("parent", payload),
);
assert.equal(
  handoffBreadcrumb({
    handoff_id: "handoff-12345678",
    source_session_id: "parent-12345678",
    child_session_id: "child-123456789",
    root_session_id: "parent-12345678",
    stage_index: 1,
    status: "ready",
    checksum: "checksum",
    envelope: {
      objective: "Continue",
      immediate_next: "Next",
      known_omissions: [],
      protected_user_constraints: [],
    },
  }),
  "parent-1 → child-12 · handoff handoff-",
);
