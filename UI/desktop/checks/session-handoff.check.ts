import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const desktopRoot = resolve(import.meta.dirname, "..");
const removedModules = [
  "src/components/SessionStageHandoffCard.tsx",
  "src/lib/session-handoff.ts",
  "src/lib/use-session-handoff.ts",
];
const ordinaryTaskSurface = [
  "src/App.tsx",
  "src/components/CodexWorkspace.tsx",
  "src/components/CodexConversationPane.tsx",
  "src/components/conversation/ConversationThread.tsx",
  "src/components/SessionThreadWorkspace.tsx",
  "src/lib/zebra-api-core.ts",
];
const forbiddenUserSurfaceTokens = [
  "SessionStageHandoffCard",
  "onCreateHandoff",
  "onPreviewHandoff",
  "createHandoff",
  "previewHandoff",
  "/handoff",
  "阶段性新线程",
  "Start next stage",
  "Preview Envelope",
];

for (const modulePath of removedModules) {
  assert.equal(existsSync(resolve(desktopRoot, modulePath)), false, `${modulePath} must stay removed`);
}

const userSurfaceSource = ordinaryTaskSurface
  .map((modulePath) => readFileSync(resolve(desktopRoot, modulePath), "utf8"))
  .join("\n");

for (const token of forbiddenUserSurfaceTokens) {
  assert.equal(userSurfaceSource.includes(token), false, `${token} must remain backend-internal`);
}
