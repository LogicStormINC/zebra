import assert from "node:assert/strict";
import {
  compactWorkspaceLabel,
  mcpPromptSchema,
  normalizeTaskLaunchConfig,
  reconcileMcpPromptSelection,
  resolveSessionLaunchConfig,
  type TaskLaunchConfig,
  validateTaskLaunchConfig,
} from "../src/lib/task-launch-config.ts";

assert.deepEqual(normalizeTaskLaunchConfig(null), { workspace: ".", policyProfile: "workspace_write", toolProfile: "general", networkProfile: "none", networkAllowlist: [], mcpAllowlist: [], mcpResourceIds: [], mcpPromptId: null, mcpPromptArguments: {}, mcpPromptSchema: null });
assert.deepEqual(normalizeTaskLaunchConfig({ workspace: "/repo", policyProfile: "full_access" }), {
  workspace: "/repo",
  policyProfile: "full_access",
  toolProfile: "general",
  networkProfile: "none",
  networkAllowlist: [],
  mcpAllowlist: [],
  mcpResourceIds: [],
  mcpPromptId: null,
  mcpPromptArguments: {},
  mcpPromptSchema: null,
});
assert.equal(normalizeTaskLaunchConfig({ workspace: "/repo", policyProfile: "unknown" }).policyProfile, "workspace_write");
assert.equal(normalizeTaskLaunchConfig({ workspace: "/repo", toolProfile: "coding" }).toolProfile, "coding");
const base = { workspace: "/repo", policyProfile: "workspace_write", toolProfile: "general", networkProfile: "none", networkAllowlist: [], mcpAllowlist: [], mcpResourceIds: [], mcpPromptId: null, mcpPromptArguments: {}, mcpPromptSchema: null } as const;
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
const prompt = { prompt_id: "mcp-prompt:11111111111111111111111111111111", name: "review", description: "Review material", available: true, arguments: [{ name: "topic", description: "Topic", required: true }, { name: "tone", description: "Tone", required: false }] };
const promptConfig = { ...base, networkProfile: "mcp-proxy-only", mcpPromptId: prompt.prompt_id, mcpPromptArguments: { topic: "durable" }, mcpPromptSchema: mcpPromptSchema(prompt) };
assert.deepEqual(normalizeTaskLaunchConfig(promptConfig), promptConfig);
assert.deepEqual(normalizeTaskLaunchConfig({ ...promptConfig, mcpPromptArguments: { topic: 1 } }).mcpPromptArguments, {});
assert.equal(validateTaskLaunchConfig(promptConfig, [], [], [prompt]), null);
assert.equal(validateTaskLaunchConfig({ ...promptConfig, mcpPromptArguments: {} }, [], [], [prompt]), "请填写 MCP Prompt 的必填参数");
assert.equal(validateTaskLaunchConfig({ ...promptConfig, mcpPromptArguments: { topic: "x", hidden: "no" } }, [], [], [prompt]), "MCP Prompt 参数包含未知字段");
assert.equal(validateTaskLaunchConfig({ ...promptConfig, mcpPromptArguments: { topic: "好".repeat(1366) } }, [], [], [prompt]), "单个 MCP Prompt 参数不能超过 4 KiB");
const manyArguments = Array.from({ length: 5 }, (_, index) => ({ name: `value-${index}`, description: "", required: false }));
const manyPrompt = { ...prompt, arguments: manyArguments };
const manyConfig = { ...promptConfig, mcpPromptSchema: mcpPromptSchema(manyPrompt), mcpPromptArguments: Object.fromEntries(manyArguments.map(({ name }) => [name, "x".repeat(4096)])) };
assert.equal(validateTaskLaunchConfig(manyConfig, [], [], [manyPrompt]), "MCP Prompt 参数总计不能超过 16 KiB");
assert.equal(validateTaskLaunchConfig({ ...promptConfig, networkProfile: "none" }, [], [], [prompt]), "选择 MCP Prompt 后需要启用仅 MCP 代理网络");
assert.equal(reconcileMcpPromptSelection(promptConfig, { status: "available", configured: true, available: true, prompt_count: 1, prompts: [prompt] }), null);
assert.deepEqual(reconcileMcpPromptSelection(promptConfig, { status: "available", configured: true, available: true, prompt_count: 0, prompts: [] }), { mcpPromptId: null, mcpPromptArguments: {}, mcpPromptSchema: null });
assert.deepEqual(reconcileMcpPromptSelection(promptConfig, { status: "available", configured: true, available: true, prompt_count: 1, prompts: [{ ...prompt, arguments: [{ name: "new-topic", description: "", required: true }] }] }), { mcpPromptId: null, mcpPromptArguments: {}, mcpPromptSchema: null });
assert.equal(compactWorkspaceLabel("/Users/operator/zebra-agent/"), "zebra-agent");
assert.equal(compactWorkspaceLabel("relative-workspace/"), "relative-workspace");
assert.equal(compactWorkspaceLabel("/"), "/");
assert.equal(compactWorkspaceLabel(""), "未配置");
assert.equal(resolveSessionLaunchConfig(base, { ...base, workspace: "" }).workspace, "/repo");
assert.equal(resolveSessionLaunchConfig(base, { ...base, workspace: "/durable" }).workspace, "/durable");
