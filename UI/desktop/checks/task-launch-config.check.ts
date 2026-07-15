import assert from "node:assert/strict";
import {
  compactWorkspaceLabel,
  normalizeTaskLaunchConfig,
  type TaskLaunchConfig,
  validateTaskLaunchConfig,
} from "../src/lib/task-launch-config.ts";

assert.deepEqual(normalizeTaskLaunchConfig(null), { workspace: ".", policyProfile: "workspace_write", toolProfile: "general", networkProfile: "none", networkAllowlist: [] });
assert.deepEqual(normalizeTaskLaunchConfig({ workspace: "/repo", policyProfile: "full_access" }), {
  workspace: "/repo",
  policyProfile: "full_access",
  toolProfile: "general",
  networkProfile: "none",
  networkAllowlist: [],
});
assert.equal(normalizeTaskLaunchConfig({ workspace: "/repo", policyProfile: "unknown" }).policyProfile, "workspace_write");
assert.equal(normalizeTaskLaunchConfig({ workspace: "/repo", toolProfile: "coding" }).toolProfile, "coding");
const base = { workspace: "/repo", policyProfile: "workspace_write", toolProfile: "general", networkProfile: "none", networkAllowlist: [] } as const;
assert.equal(validateTaskLaunchConfig({ ...base, workspace: "  " }), "请先填写任务工作区路径");
assert.equal(validateTaskLaunchConfig({ ...base, policyProfile: "unknown" } as TaskLaunchConfig), "不支持当前权限策略");
assert.equal(validateTaskLaunchConfig({ ...base, toolProfile: "unknown" } as TaskLaunchConfig), "不支持当前工具配置");
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "domain-allowlist" }), "域名白名单至少需要一个域名");
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "domain-allowlist", networkAllowlist: ["docs.example.com"] }), null);
assert.equal(validateTaskLaunchConfig({ ...base, networkProfile: "domain-allowlist", networkAllowlist: ["https://docs.example.com"] }), "域名白名单仅接受裸域名");
assert.equal(validateTaskLaunchConfig({ ...base, toolProfile: "coding" }), null);
assert.equal(compactWorkspaceLabel("/Users/operator/zebra-agent/"), "zebra-agent");
assert.equal(compactWorkspaceLabel("relative-workspace/"), "relative-workspace");
assert.equal(compactWorkspaceLabel("/"), "/");
assert.equal(compactWorkspaceLabel(""), "未配置");
