import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const composer = readFileSync(new URL("../src/components/conversation/ConversationComposer.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/components/CodexConversationPane.styles.ts", import.meta.url), "utf8");

assert.match(composer, /className=\{styles\.composerCard\}/);
assert.match(composer, /autoSize=\{\{ minRows: 1, maxRows: 6 \}\}/);
assert.match(composer, /<ComposerAttachments[\s\S]+<TaskLaunchControls/);
assert.doesNotMatch(styles, /min-height: (126|180)px/);
assert.match(styles, /max-height: min\(240px, 42dvh\)/);
assert.match(styles, /\.ant-sender-content \{\s+padding: 4px 8px 2px;/);
assert.match(styles, /composerFooter: css`\s+width: 100%;\s+min-height: 38px;/);

console.log("compact composer layout check passed");
