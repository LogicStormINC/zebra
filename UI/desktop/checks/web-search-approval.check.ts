import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const source = readFileSync(
  fileURLToPath(new URL("../src/components/SessionApprovalPanel.tsx", import.meta.url)),
  "utf8",
);
const sharedCard = readFileSync(
  fileURLToPath(new URL("../../packages/task-ui/src/react/ApprovalCard.tsx", import.meta.url)),
  "utf8",
);

assert.match(source, /ApprovalCard/);
assert.match(source, /renderExtraDetails/);
assert.match(source, /context\?\.tool_name === "web\.search"/);
assert.match(source, /label="查询"/);
assert.match(source, /label="结果上限"/);
assert.doesNotMatch(source, /onSearch|search page|搜索页面/);
assert.doesNotMatch(sharedCard, /web\.search/);
assert.doesNotMatch(sharedCard, /arguments|output|policyReason/);
