import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const apiSource = readFileSync(new URL("../src/lib/zebra-api-core.ts", import.meta.url), "utf8");
const controlsSource = readFileSync(new URL("../src/components/conversation/TaskLaunchControls.tsx", import.meta.url), "utf8");

assert.match(apiSource, /"\/capabilities\/mcp\/prompts"/u);
assert.match(appSource, /queryKey: \["mcp-prompts"[\s\S]*?enabled: false/u);
assert.equal(appSource.match(/mcp_prompt_id: launchConfig\.mcpPromptId/g)?.length, 1);
assert.equal(appSource.match(/mcp_prompt_arguments: launchConfig\.mcpPromptId/g)?.length, 1);
assert.doesNotMatch(apiSource.match(/appendMessage:[\s\S]*?commit:/u)?.[0] ?? "", /mcp_prompt/u);
assert.match(controlsSource, /editable && config\.networkProfile === "mcp-proxy-only"/u);

console.log("mcp-prompt-launch check passed");
