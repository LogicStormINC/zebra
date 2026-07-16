import assert from "node:assert/strict";
import { availableMcpResourceIds, availableMcpToolNames, projectMcpCapabilities } from "../src/lib/mcp-capabilities.ts";

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
  resource_count: 2,
  servers: [],
}, false, null);
assert.equal(available.summary, "2 个服务器，3 个工具，2 个资源");
assert.equal(available.state, "available");
assert.deepEqual(availableMcpToolNames({
  status: "available",
  configured: true,
  available: true,
  server_count: 1,
  tool_count: 1,
  resource_count: 1,
  servers: [{ name: "docs", tool_count: 1, tools: [{ name: "search", description: "", input_fields: [] }], resource_count: 1, resources: [{ resource_id: "resource-1", name: "brief", description: "", mime_type: "text/plain", size_bytes: 12 }] }],
}), ["mcp.docs.search"]);
assert.deepEqual(availableMcpResourceIds({
  status: "available",
  configured: true,
  available: true,
  server_count: 1,
  tool_count: 0,
  resource_count: 1,
  servers: [{ name: "docs", tool_count: 0, tools: [], resource_count: 1, resources: [{ resource_id: "resource-1", name: "brief", description: "", mime_type: "text/plain", size_bytes: 12 }] }],
}), ["resource-1"]);

assert.equal(projectMcpCapabilities(undefined, false, "认证失败").summary, "认证失败");
assert.equal(projectMcpCapabilities(undefined, false, null).state, "unavailable");

console.log("mcp-capabilities check passed");
