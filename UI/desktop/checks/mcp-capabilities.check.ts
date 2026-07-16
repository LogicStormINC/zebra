import assert from "node:assert/strict";
import { projectMcpCapabilities } from "../src/lib/mcp-capabilities.ts";

assert.deepEqual(projectMcpCapabilities(undefined, true, null), {
  state: "checking",
  label: "检查中",
  color: "gold",
  summary: "正在读取 MCP 能力清单。",
});

const available = projectMcpCapabilities({
  status: "available",
  configured: true,
  available: true,
  server_count: 2,
  tool_count: 3,
  servers: [],
}, false, null);
assert.equal(available.summary, "2 个服务器，3 个工具");
assert.equal(available.state, "available");

assert.equal(projectMcpCapabilities(undefined, false, "认证失败").summary, "认证失败");
assert.equal(projectMcpCapabilities(undefined, false, null).state, "unavailable");

console.log("mcp-capabilities check passed");
