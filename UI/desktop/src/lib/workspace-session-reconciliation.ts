import dayjs from "dayjs";
import type { RecentSessionSummary, SessionSummary } from "../types";
import type { ConversationSeed } from "./chat-surface";

export interface WorkspaceSessionIndex {
  conversations: ConversationSeed[];
  sessionIds: Record<string, string>;
  hiddenSessionIds?: string[];
}

export interface ReconciledWorkspaceSessionIndex extends WorkspaceSessionIndex {
  sessionSummaries: Record<string, SessionSummary>;
}

export function reconcileWorkspaceSessionIndex(
  local: WorkspaceSessionIndex,
  recentSessions: RecentSessionSummary[],
): ReconciledWorkspaceSessionIndex {
  const drafts: ConversationSeed[] = [];
  const boundBySessionId = new Map<string, ConversationSeed>();
  const hiddenSessionIds = new Set(local.hiddenSessionIds ?? []);
  for (const conversation of local.conversations) {
    const sessionId = local.sessionIds[conversation.key];
    if (!sessionId) {
      drafts.push(conversation);
    } else if (!hiddenSessionIds.has(sessionId) && !boundBySessionId.has(sessionId)) {
      boundBySessionId.set(sessionId, conversation);
    }
  }

  const conversations = [...drafts];
  const sessionIds: Record<string, string> = {};
  const sessionSummaries: Record<string, SessionSummary> = {};
  const importedSessionIds = new Set<string>();
  for (const summary of recentSessions) {
    if (importedSessionIds.has(summary.session_id) || hiddenSessionIds.has(summary.session_id)) continue;
    importedSessionIds.add(summary.session_id);
    const localConversation = boundBySessionId.get(summary.session_id);
    const key = localConversation?.key ?? `session:${summary.session_id}`;
    conversations.push({
      key,
      label: summary.title,
      group: dayjs(summary.updated_at).format("HH:mm"),
    });
    sessionIds[key] = summary.session_id;
    sessionSummaries[key] = summary;
    boundBySessionId.delete(summary.session_id);
  }

  // A bounded recent list cannot prove that an older local binding is stale.
  for (const [sessionId, conversation] of boundBySessionId) {
    conversations.push(conversation);
    sessionIds[conversation.key] = sessionId;
  }
  return { conversations, sessionIds, hiddenSessionIds: [...hiddenSessionIds], sessionSummaries };
}
