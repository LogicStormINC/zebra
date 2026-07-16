import assert from "node:assert/strict";
import {
  compactWorkspaceLabel,
  normalizeTaskLaunchConfig,
  type TaskLaunchConfig,
  validateTaskLaunchConfig,
} from "../src/lib/task-launch-config.ts";

assert.deepEqual(normalizeTaskLaunchConfig(null), { workspace: ".", policyProfile: "workspace_write", toolProfile: "general", networkProfile: "none", networkAllowlist: [], mcpAllowlist: [], mcpResourceIds: [] });
assert.deepEqual(normalizeTaskLaunchConfig({ workspace: "/repo", policyProfile: "full_access" }), {
  workspace: "/repo",
  policyProfile: "full_access",
  toolProfile: "general",
  networkProfile: "none",
  networkAllowlist: [],
  mcpAllowlist: [],
  mcpResourceIds: [],
});
assert.equal(normalizeTaskLaunchConfig({ workspace: "/repo", policyProfile: "unknown" }).policyProfile, "workspace_write");
assert.equal(normalizeTaskLaunchConfig({ workspace: "/repo", toolProfile: "coding" }).toolProfile, "coding");
const base = { workspace: "/repo", policyProfile: "workspace_write", toolProfile: "general", networkProfile: "none", networkAllowlist: [], mcpAllowlist: [], mcpResourceIds: [] } as const;
assert.equal(validateTaskLaunchConfig({ ...base, workspace: "  " }), "请先填写任务工作区路径");
assert.equal(validateTaskLaunchConfig({ ...base, policyProfile: "unknown" } as TaskLaunchConfig), "不支持当前权限策略");
assert.equal(validateTaskLaunchConfig({ ...base, toolProfile: "unknown" } as TaskLaunchConfig), "不支持当前工具配置");
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "domain-allowlist" }), "域名白名单至少需要一个域名");
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "domain-allowlist", networkAllowlist: ["docs.example.com"] }), null);
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "domain-allowlist", networkAllowlist: ["https://docs.example.com"] }), "域名白名单仅接受裸域名");
assert.equal(validateTaskLaunchConfig({ ...base, toolProfile: "coding" }), null);
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "mcp-proxy-only", mcpAllowlist: ["mcp.docs.search"] }, ["mcp.docs.search"]), null);
assert.equal(validateTaskLaunchConfig({ ...base, mcpAllowlist: ["mcp.docs.search"] }), "选择 MCP 工具后需要启用仅 MCP 代理网络");
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "mcp-proxy-only", mcpAllowlist: ["mcp.docs.removed"] }, ["mcp.docs.search"]), "已选择的 MCP 工具当前不可用，请重新选择");
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "mcp-proxy-only", mcpResourceIds: ["resource-1"] }, [], ["resource-1"]), null);
assert.equal(validateTaskLaunchConfig({ ...base, mcpResourceIds: ["resource-1"] }), "选择 MCP 资源后需要启用仅 MCP 代理网络");
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "mcp-proxy-only", mcpResourceIds: ["removed"] }, [], ["resource-1"]), "已选择的 MCP 资源当前不可用，请重新选择");
assert.equal(compactWorkspaceLabel("/Users/operator/zebra-agent/"), "zebra-agent");
assert.equal(compactWorkspaceLabel("relative-workspace/"), "relative-workspace");
assert.equal(compactWorkspaceLabel("/"), "/");
assert.equal(compactWorkspaceLabel(""), "未配置");
