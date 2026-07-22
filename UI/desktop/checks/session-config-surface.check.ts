import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const composerSource = readFileSync(new URL("../src/components/conversation/ConversationComposer.tsx", import.meta.url), "utf8");
const controlsSource = readFileSync(new URL("../src/components/conversation/TaskLaunchControls.tsx", import.meta.url), "utf8");
const workspaceSource = readFileSync(new URL("../src/components/SessionThreadWorkspace.tsx", import.meta.url), "utf8");
const idleSource = readFileSync(new URL("../src/components/conversation/WorkspaceIdle.tsx", import.meta.url), "utf8");
const envCardSource = readFileSync(new URL("../src/components/conversation/ExecutionEnvironmentCard.tsx", import.meta.url), "utf8");

// The editable launch summary renders in the thread composer, but is suppressed
// in the idle variant where the ExecutionEnvironmentCard shows the config instead.
assert.match(composerSource, /launchEditable && variant !== "idle" \? \([\s\S]*?<TaskLaunchSummary/u);
assert.match(composerSource, /<TaskLaunchSummary[\s\S]*?\n\s+editable\n[\s\S]*?\/>/u);
// The idle workspace surfaces the execution environment as a four-cell card.
assert.match(idleSource, /<ExecutionEnvironmentCard[\s\S]*?config=\{launchConfig\}/u);
assert.match(envCardSource, /locale\.executionEnvironment/u);
assert.doesNotMatch(controlsSource, /effectiveConfig/u);
assert.doesNotMatch(controlsSource, /\) : <span className=\{launchStyles\.staticBadge\}>/u);
for (const label of ["MCP", "Prompt", "材料", "模型"]) {
  assert.match(workspaceSource, new RegExp(`<span>${label}<\\/span>`, "u"));
}
assert.match(workspaceSource, /source_type === "mcp_prompt"/u);
assert.doesNotMatch(workspaceSource, /capturedPrompt\.source_id/u);

console.log("session-config-surface check passed");
