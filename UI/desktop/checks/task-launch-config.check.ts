import assert from "node:assert/strict";
import {
  compactWorkspaceLabel,
  normalizeTaskLaunchConfig,
  type TaskLaunchConfig,
  validateTaskLaunchConfig,
} from "../src/lib/task-launch-config.ts";

assert.deepEqual(normalizeTaskLaunchConfig(null), { workspace: ".", policyProfile: "workspace_write" });
assert.deepEqual(normalizeTaskLaunchConfig({ workspace: "/repo", policyProfile: "full_access" }), {
  workspace: "/repo",
  policyProfile: "full_access",
});
assert.equal(normalizeTaskLaunchConfig({ workspace: "/repo", policyProfile: "unknown" }).policyProfile, "workspace_write");
assert.equal(validateTaskLaunchConfig({ workspace: "  ", policyProfile: "workspace_write" }), "请先填写任务工作区路径");
assert.equal(validateTaskLaunchConfig({ workspace: "/repo", policyProfile: "unknown" } as TaskLaunchConfig), "不支持当前权限策略");
assert.equal(validateTaskLaunchConfig({ workspace: "/repo", policyProfile: "full_access" }), null);
assert.equal(compactWorkspaceLabel("/Users/operator/zebra-agent/"), "zebra-agent");
assert.equal(compactWorkspaceLabel("relative-workspace/"), "relative-workspace");
assert.equal(compactWorkspaceLabel("/"), "/");
assert.equal(compactWorkspaceLabel(""), "未配置");
