import dayjs from "dayjs";
import { useCallback, useEffect, useRef, useState } from "react";
import { useXConversations } from "@ant-design/x-sdk";
import type { SessionSummary } from "../types";
import type { ConversationSeed } from "./chat-surface";
import type { ZebraApiClient } from "./zebra-api";
import { reconcileWorkspaceSessionIndex } from "./workspace-session-reconciliation";

const STORAGE_KEY = "zebra-agent-desktop.workspace-index.v1";
const MAX_CONVERSATIONS = 100;

interface StoredWorkspaceIndex {
  conversations: ConversationSeed[];
  sessionIds: Record<string, string>;
  hiddenSessionIds: string[];
}

const EMPTY_INDEX: StoredWorkspaceIndex = {
  conversations: [],
  sessionIds: {},
  hiddenSessionIds: [],
};

function isConversation(value: unknown): value is ConversationSeed {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  return typeof item.key === "string" && typeof item.label === "string" && typeof item.group === "string";
}

function readWorkspaceIndex(): StoredWorkspaceIndex {
  if (typeof window === "undefined") return EMPTY_INDEX;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return EMPTY_INDEX;

  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const conversations = Array.isArray(parsed.conversations)
      ? parsed.conversations.filter(isConversation).slice(0, MAX_CONVERSATIONS)
      : [];
    const conversationKeys = new Set(conversations.map((item) => item.key));
    const sessionIds = Object.fromEntries(
      Object.entries(parsed.sessionIds ?? {}).filter(
        ([key, value]) => conversationKeys.has(key) && typeof value === "string" && value.length > 0,
      ),
    ) as Record<string, string>;
    const hiddenSessionIds = Array.isArray(parsed.hiddenSessionIds)
      ? parsed.hiddenSessionIds.filter((value): value is string => typeof value === "string").slice(0, MAX_CONVERSATIONS)
      : [];
    return { conversations, sessionIds, hiddenSessionIds };
  } catch {
    return EMPTY_INDEX;
  }
}

function newConversation(label: string): ConversationSeed {
  return {
    key: crypto.randomUUID(),
    label,
    group: dayjs().format("HH:mm"),
  };
}

export function useWorkspaceSessionIndex(api: ZebraApiClient, fallbackSessionId: string) {
  const [initialIndex] = useState(readWorkspaceIndex);
  const { conversations, addConversation, setConversations } = useXConversations({
    defaultConversations: initialIndex.conversations,
  });
  const [sessionIds, setSessionIds] = useState<Record<string, string>>(initialIndex.sessionIds);
  const [hiddenSessionIds, setHiddenSessionIds] = useState(initialIndex.hiddenSessionIds);
  const [sessionSummaries, setSessionSummaries] = useState<Record<string, SessionSummary | null>>({});
  const migrationAttempted = useRef(false);

  useEffect(() => {
    let cancelled = false;
    void api.sessions(MAX_CONVERSATIONS).then(({ sessions }) => {
      if (cancelled) return;
      const reconciled = reconcileWorkspaceSessionIndex(
        { conversations: conversations as ConversationSeed[], sessionIds, hiddenSessionIds },
        sessions,
      );
      setConversations(reconciled.conversations);
      setSessionIds(reconciled.sessionIds);
      setSessionSummaries((current) => ({ ...current, ...reconciled.sessionSummaries }));
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [api]);

  useEffect(() => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ conversations: conversations.slice(0, MAX_CONVERSATIONS), sessionIds, hiddenSessionIds }),
    );
  }, [conversations, hiddenSessionIds, sessionIds]);

  useEffect(() => {
    let cancelled = false;
    const entries = Object.entries(sessionIds);
    void Promise.all(
      entries.map(async ([key, sessionId]) => {
        try {
          return [key, await api.session(sessionId)] as const;
        } catch {
          return [key, null] as const;
        }
      }),
    ).then((summaries) => {
      if (!cancelled) setSessionSummaries(Object.fromEntries(summaries));
    });
    return () => {
      cancelled = true;
    };
  }, [api, sessionIds]);

  useEffect(() => {
    if (migrationAttempted.current || conversations.length > 0 || !fallbackSessionId) return;
    migrationAttempted.current = true;
    void api.session(fallbackSessionId).then((summary) => {
      const conversation = newConversation(summary.title);
      addConversation(conversation);
      setSessionIds({ [conversation.key]: fallbackSessionId });
      setSessionSummaries({ [conversation.key]: summary });
    }).catch(() => undefined);
  }, [addConversation, api, conversations.length, fallbackSessionId]);

  const createIndexedConversation = useCallback((label: string) => {
    const conversation = newConversation(label);
    addConversation(conversation);
    return conversation.key;
  }, [addConversation]);

  const renameConversation = useCallback((key: string, label: string) => {
    setConversations(conversations.map((item) => item.key === key ? { ...item, label } : item));
  }, [conversations, setConversations]);

  const removeIndexedConversation = useCallback((key: string) => {
    const sessionId = sessionIds[key];
    if (sessionId) {
      setHiddenSessionIds((current) => current.includes(sessionId) ? current : [...current, sessionId]);
    }
    setConversations(conversations.filter((item) => item.key !== key));
    setSessionIds((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    setSessionSummaries((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
  }, [conversations, sessionIds, setConversations]);

  return {
    conversations: conversations as ConversationSeed[],
    createIndexedConversation,
    removeIndexedConversation,
    renameConversation,
    sessionIds,
    sessionSummaries,
    setSessionIds,
    setSessionSummaries,
  };
}
