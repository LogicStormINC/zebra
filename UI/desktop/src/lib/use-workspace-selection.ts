import { useEffect, useState } from "react";
import type { ConversationSeed } from "./chat-surface";

const STORAGE_KEY = "zebra-agent-desktop.workspace-selection.v1";

export function resolveStoredConversation(
  storedKey: string | null,
  conversations: ConversationSeed[],
  homeKey: string,
): string {
  return storedKey && conversations.some((item) => item.key === storedKey) ? storedKey : homeKey;
}

export function useWorkspaceSelection(conversations: ConversationSeed[], homeKey: string) {
  const [currentConversation, setCurrentConversation] = useState(() => {
    const storedKey = typeof window === "undefined" ? null : window.localStorage.getItem(STORAGE_KEY);
    return resolveStoredConversation(storedKey, conversations, homeKey);
  });

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, currentConversation);
  }, [currentConversation]);

  return [currentConversation, setCurrentConversation] as const;
}
