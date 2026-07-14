import type { ConversationSeed } from "./chat-surface";
import type { SessionSummary } from "../types";

export const UNBOUND_PROJECT_ID = "project:unbound";

export interface WorkspaceProject {
  id: string;
  workspaceRoot: string | null;
  conversationKeys: string[];
  configured: boolean;
}

export function workspaceProjectId(workspaceRoot: string): string {
  const normalized = normalizeWorkspaceRoot(workspaceRoot);
  return normalized ? `project:${normalized}` : UNBOUND_PROJECT_ID;
}

export function projectWorkspaceNavigation(
  conversations: ConversationSeed[],
  sessionSummaries: Record<string, SessionSummary | null>,
  launchWorkspace: string,
): WorkspaceProject[] {
  const configuredRoot = normalizeWorkspaceRoot(launchWorkspace);
  const projects = new Map<string, WorkspaceProject>();
  if (configuredRoot) addProject(projects, configuredRoot, true);

  for (const conversation of conversations) {
    const workspaceRoot = normalizeWorkspaceRoot(
      sessionSummaries[conversation.key]?.workspace?.workspace_root ?? "",
    );
    const project = addProject(projects, workspaceRoot || null, workspaceRoot === configuredRoot);
    project.conversationKeys.push(conversation.key);
  }

  if (projects.size === 0) addProject(projects, null, false);
  return [...projects.values()];
}

function addProject(
  projects: Map<string, WorkspaceProject>,
  workspaceRoot: string | null,
  configured: boolean,
): WorkspaceProject {
  const id = workspaceRoot ? workspaceProjectId(workspaceRoot) : UNBOUND_PROJECT_ID;
  const existing = projects.get(id);
  if (existing) {
    existing.configured ||= configured;
    return existing;
  }
  const project = { id, workspaceRoot, conversationKeys: [], configured };
  projects.set(id, project);
  return project;
}

function normalizeWorkspaceRoot(workspaceRoot: string): string {
  const trimmed = workspaceRoot.trim();
  if (!trimmed || trimmed === "/") return trimmed;
  return trimmed.replace(/\/+$/, "");
}
