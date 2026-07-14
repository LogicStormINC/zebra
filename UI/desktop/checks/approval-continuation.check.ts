import assert from "node:assert/strict";
import { decideActiveApproval } from "../src/lib/approval-continuation.ts";

const calls: string[] = [];
const api = {
  approve: async () => { calls.push("approve"); return {}; },
  reject: async () => { calls.push("reject"); return {}; },
  resume: async () => { calls.push("resume"); return {}; },
};
const approval = {
  approval_id: "approval-113",
  session_id: "session-113",
};

await decideActiveApproval(api, approval, "approve");
assert.deepEqual(calls, ["approve", "resume"]);

calls.length = 0;
await decideActiveApproval(api, approval, "reject");
assert.deepEqual(calls, ["reject"]);
