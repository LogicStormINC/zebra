import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { formatTokenCount, projectContextUsage } from "../src/lib/context-usage.ts";
import { appendBoundedSupplement, type QueuedSupplement } from "../src/lib/use-supplement-queue.ts";
import type { SessionEvent } from "../src/types.ts";

const composer = readFileSync(new URL("../src/components/conversation/ConversationComposer.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/components/CodexConversationPane.styles.ts", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const supplementQueue = readFileSync(new URL("../src/lib/use-supplement-queue.ts", import.meta.url), "utf8");

assert.match(composer, /className=\{styles\.composerCard\}/);
assert.match(composer, /autoSize=\{\{ minRows: 1, maxRows: 6 \}\}/);
assert.match(composer, /<ComposerAttachments[\s\S]+<TaskLaunchControls/);
assert.match(composer, /<ContextUsageIndicator events=\{events\}/);
assert.match(composer, /const action = hasInput \? "send" : isRequesting \? "pause"[\s\S]+\? "resume" : "send"/u);
assert.match(composer, /loading=\{false\}/);
assert.doesNotMatch(styles, /min-height: (126|180)px/);
assert.match(styles, /max-height: min\(240px, 42dvh\)/);
assert.match(styles, /\.ant-sender-content \{\s+padding: 4px 8px 2px;/);
assert.match(styles, /composerFooter: css`\s+width: 100%;\s+min-height: 38px;/);
assert.match(app, /if \(isRequesting && conversationToSessionId\[conversationKey\]\)/);
assert.match(app, /while \(supplementQueue\.peek\(conversationKey\)\)/);
assert.match(app, /local-supplement-/);
assert.match(supplementQueue, /MAX_QUEUED_SUPPLEMENTS = 8/);
assert.match(supplementQueue, /已排队，将在当前步骤结束后处理/);

const event = (sequence: number, eventType: string, payload: Record<string, unknown>): SessionEvent => ({
  event_id: `event-${sequence}`,
  sequence,
  event_type: eventType,
  actor: "harness",
  created_at: "2026-09-14T00:00:00Z",
  payload,
});
const usage = projectContextUsage([
  event(1, "model_request_started", { estimated_input_tokens: 9_500, input_token_limit: 105_000 }),
  event(2, "model_response_received", {
    input_tokens: 10_100,
    input_token_limit: 105_000,
    prompt_cache_hit_tokens: 9_680,
    prompt_cache_miss_tokens: 320,
    provider: "deepseek",
    resolved_model: "deepseek-flash",
    reasoning_effort: "high",
  }),
]);
assert.equal(usage.usedTokens, 10_100);
assert.equal(usage.limitTokens, 105_000);
assert.equal(usage.cacheHitRate, 0.968);
assert.equal(usage.modelLabel, "DeepSeek/deepseek-flash");
assert.equal(usage.reasoningLabel, "最高");
assert.equal(formatTokenCount(105_000), "10.5万");

const supplement = (key: string): QueuedSupplement => ({ key, content: key, attachments: [] });
const fullQueue = Array.from({ length: 8 }, (_, index) => supplement(String(index)));
assert.equal(appendBoundedSupplement(fullQueue, supplement("overflow")), null);
assert.deepEqual(appendBoundedSupplement([], supplement("first")), [supplement("first")]);

console.log("compact composer layout check passed");
