import assert from "node:assert/strict";
import { projectRuntimeConnection } from "../src/lib/runtime-connection.ts";
import { projectWorkspaceLabel } from "../src/lib/workspace-projection.ts";

assert.equal(projectRuntimeConnection(undefined, undefined, true), "checking");
assert.equal(projectRuntimeConnection("ok", "zebra-agent-api", false), "connected");
assert.equal(projectRuntimeConnection("ok", "another-service", false), "disconnected");
assert.equal(projectRuntimeConnection(undefined, undefined, false), "disconnected");
assert.equal(projectRuntimeConnection("degraded", "zebra-agent-api", false), "disconnected");
assert.equal(projectWorkspaceLabel(undefined, "未绑定"), "未绑定");
assert.equal(projectWorkspaceLabel("/repo/zebra-agent", "未绑定"), "zebra-agent");
assert.equal(projectWorkspaceLabel("C:\\repo\\zebra-agent", "未绑定"), "zebra-agent");
