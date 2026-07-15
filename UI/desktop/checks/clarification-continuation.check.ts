import assert from "node:assert/strict";
import { buildClarificationResponsePayload } from "../src/lib/clarification-continuation.ts";

assert.deepEqual(buildClarificationResponsePayload(" clarification-1 ", " Operators "), {
  content: "Operators",
  clarification_id: "clarification-1",
});
assert.throws(() => buildClarificationResponsePayload("", "Operators"));
