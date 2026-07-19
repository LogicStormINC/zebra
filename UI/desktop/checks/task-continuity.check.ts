import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const desktopRoot = resolve(import.meta.dirname, "..");
const coreApi = readFileSync(resolve(desktopRoot, "src/lib/zebra-api-core.ts"), "utf8");
const app = readFileSync(resolve(desktopRoot, "src/App.tsx"), "utf8");

for (const route of [
  '"/tasks"',
  "`/tasks?limit=${limit}`",
  "`/tasks/${taskId}`",
  "`/tasks/${sessionId}/stream`",
  "`/tasks/${sessionId}/messages`",
  "`/tasks/${sessionId}/cancel`",
  "`/tasks/${sessionId}/suspend`",
  "`/tasks/${sessionId}/resume`",
]) {
  assert.equal(coreApi.includes(route), true, `Desktop must use stable Task route ${route}`);
}

assert.equal(coreApi.includes("/sessions"), false, "ordinary Desktop core must not bind Session APIs");
assert.equal(
  app.includes("isAppendToTerminalError"),
  false,
  "terminal follow-up must stay on the same Task instead of creating a replacement conversation",
);
