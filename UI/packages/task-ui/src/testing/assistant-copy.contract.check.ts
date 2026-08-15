import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// W45-UI-02 assistant-copy contract:
// AssistantMessage owns an optional built-in copy action. Consumers whose
// toolbar already owns "copy" (FinOS) suppress it via showCopyAction={false};
// the default stays true so existing consumers render identically.
const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "../react/AssistantMessage.tsx"), "utf8");

assert.match(src, /showCopyAction\?: boolean;/, "props must declare showCopyAction");
assert.match(src, /showCopyAction = true/, "default must stay true (backward compatible)");
assert.match(src, /\.\.\.\(showCopyAction\s*\?/, "built-in copy must be conditional on showCopyAction");
assert.match(src, /actionRender: <Actions\.Copy/, "built-in Actions.Copy must be retained");
assert.match(src, /\{renderMessageActions\?\.\(message\)\}/, "consumer actions must render unconditionally");

console.log("assistant-copy contract OK: default true, false suppresses built-in copy only");
