import assert from "node:assert/strict";
import type { RecentSessionSummary } from "../src/types/session.ts";
import { reconcileWorkspaceSessionIndex } from "../src/lib/workspace-session-reconciliation.ts";

const newest = session("session-new", "Newest", "2026-07-14T02:02:00Z");
const older = session("session-old", "Older", "2026-07-14T02:01:00Z");
const hidden = session("session-hidden", "Hidden", "2026-07-14T02:03:00Z");
const result = reconcileWorkspaceSessionIndex(
  {
    conversations: [
      { key: "draft", label: "Unsaved draft", group: "10:00" },
      { key: "existing", label: "Old local title", group: "09:00" },
      { key: "duplicate", label: "Duplicate", group: "08:00" },
      { key: "outside-window", label: "Outside recent window", group: "07:00" },
      { key: "hidden", label: "Hidden local binding", group: "06:00" },
    ],
    sessionIds: {
      existing: "session-old",
      duplicate: "session-old",
      "outside-window": "session-ancient",
      hidden: "session-hidden",
    },
    hiddenSessionIds: ["session-hidden"],
  },
  [hidden, newest, older, newest],
);

assert.deepEqual(result.conversations.map(({ key }) => key), [
  "draft",
  "session:session-new",
  "existing",
  "outside-window",
]);
assert.equal(result.conversations[2]?.label, "Older");
assert.deepEqual(result.sessionIds, {
  "session:session-new": "session-new",
  existing: "session-old",
  "outside-window": "session-ancient",
});
assert.equal(result.sessionSummaries.existing, older);
assert.deepEqual(result.hiddenSessionIds, ["session-hidden"]);

function session(sessionId: string, title: string, updatedAt: string): RecentSessionSummary {
  return {
    session_id: sessionId,
    title,
    status: "ready",
    current_sequence: 0,
    created_at: updatedAt,
    updated_at: updatedAt,
  };
}
