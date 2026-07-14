import assert from "node:assert/strict";
import type { SessionSummary } from "../src/types/session.ts";
import {
  projectWorkspaceNavigation,
  UNBOUND_PROJECT_ID,
  workspaceProjectId,
} from "../src/lib/workspace-projects.ts";

const conversations = [
  { key: "repo-a-new", label: "A new", group: "10:00" },
  { key: "draft", label: "Draft", group: "09:59" },
  { key: "repo-b", label: "B", group: "09:58" },
  { key: "repo-a-old", label: "A old", group: "09:57" },
];
const summaries: Record<string, SessionSummary | null> = {
  "repo-a-new": session("/work/repo-a/"),
  draft: null,
  "repo-b": session("/work/repo-b"),
  "repo-a-old": session("/work/repo-a"),
};

const projects = projectWorkspaceNavigation(conversations, summaries, "/work/repo-b/");

assert.deepEqual(projects.map(({ id }) => id), [
  workspaceProjectId("/work/repo-b"),
  workspaceProjectId("/work/repo-a"),
  UNBOUND_PROJECT_ID,
]);
assert.deepEqual(projects[0]?.conversationKeys, ["repo-b"]);
assert.deepEqual(projects[1]?.conversationKeys, ["repo-a-new", "repo-a-old"]);
assert.deepEqual(projects[2]?.conversationKeys, ["draft"]);
assert.equal(projects[0]?.configured, true);
assert.equal(projectWorkspaceNavigation([], {}, "")[0]?.id, UNBOUND_PROJECT_ID);

const sameNameProjects = projectWorkspaceNavigation(
  [
    { key: "one", label: "One", group: "10:00" },
    { key: "two", label: "Two", group: "09:00" },
  ],
  { one: session("/work/one/repo"), two: session("/work/two/repo") },
  "",
);
assert.equal(sameNameProjects.length, 2);

function session(workspaceRoot: string): SessionSummary {
  return {
    session_id: crypto.randomUUID(),
    title: "Session",
    status: "ready",
    current_sequence: 0,
    workspace: {
      workspace_root: workspaceRoot,
      status: "prepared",
      current_sequence: 0,
      prepared_at: "2026-07-14T00:00:00Z",
      updated_at: "2026-07-14T00:00:00Z",
      policy_profile: "workspace_write",
      last_attempt_number: 0,
    },
  };
}
