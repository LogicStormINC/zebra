import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// W45-UI-01 theme-token contract:
// Shared task-ui components must consume semantic --task-ui-* CSS variables
// instead of hardcoding the Zebra dark palette, so light consumers (FinOS)
// can restyle them from a single root. Every usage must keep a dark fallback
// so Zebra Desktop renders unchanged until a consumer overrides a token.
const COMPONENTS = [
  "AssistantMessage.tsx",
  "ClarificationCard.tsx",
  "ExecutionDisclosure.tsx",
  "NewContentCue.tsx",
  "RuntimeActivityCard.tsx",
  "TaskPlan.tsx",
  "ToolCallGroup.tsx",
];

// Attachment 4.3 token set, plus success (completed tool status default).
const REQUIRED_TOKENS = [
  "--task-ui-surface",
  "--task-ui-surface-muted",
  "--task-ui-text",
  "--task-ui-text-muted",
  "--task-ui-border",
  "--task-ui-accent",
  "--task-ui-danger",
  "--task-ui-success",
];

const here = dirname(fileURLToPath(import.meta.url));
const sources = new Map(
  COMPONENTS.map((name) => [name, readFileSync(join(here, "../react", name), "utf8")]),
);

for (const [name, raw] of sources) {
  // Strip var(...) fallback bodies so dark defaults are not flagged.
  const src = raw.replace(/var\(--task-ui-[a-z-]+,\s*[^)]*\)/g, "var(--task-ui-x)");
  assert.ok(!/rgba\(\s*255,\s*255,\s*255/.test(src), `${name} hardcodes white rgba`);
  assert.ok(!/#f5a623|#f2a65a|#f28b82|#8fbc8f|#8f8f8f/i.test(src), `${name} hardcodes dark palette`);
  assert.ok(!/var\(--zebra-(text|brand|surface)-/.test(raw), `${name} depends on Zebra Desktop color tokens`);
  for (const match of raw.matchAll(/var\((--task-ui-[a-z-]+)/g)) {
    assert.match(
      raw.slice(match.index!, match.index! + 160),
      /var\(--task-ui-[a-z-]+,\s*[^)]+/,
      `${name}: ${match[1]} must keep a dark fallback`,
    );
  }
}

const all = [...sources.values()].join("\n");
for (const token of REQUIRED_TOKENS) {
  assert.ok(all.includes(token), `${token} must be referenced by the components`);
}

console.log(
  `theme-token contract OK: ${COMPONENTS.length} components tokenized, ${REQUIRED_TOKENS.length} tokens referenced`,
);
