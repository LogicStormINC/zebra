import { useCallback, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "./chat-surface";
import type { AttachmentPayload } from "./text-attachments";

const MAX_QUEUED_SUPPLEMENTS = 8;

export interface QueuedSupplement {
  attachments: AttachmentPayload[];
  content: string;
  key: string;
}

export function appendBoundedSupplement(
  queue: QueuedSupplement[],
  supplement: QueuedSupplement,
): QueuedSupplement[] | null {
  return queue.length >= MAX_QUEUED_SUPPLEMENTS ? null : [...queue, supplement];
}

export function useSupplementQueue(currentConversation: string, durableMessages: ChatMessage[]) {
  const queuesRef = useRef<Record<string, QueuedSupplement[]>>({});
  const [queues, setQueues] = useState<Record<string, QueuedSupplement[]>>({});
  const messages = useMemo(() => [
    ...durableMessages,
    ...(queues[currentConversation] ?? []).map<ChatMessage>((item) => ({
      key: item.key,
      role: "user",
      status: "success",
      content: `${item.content}\n\n（已排队，将在当前步骤结束后处理）`,
    })),
  ], [currentConversation, durableMessages, queues]);

  const enqueue = useCallback((conversationKey: string, content: string, attachments: AttachmentPayload[]) => {
    const queue = queuesRef.current[conversationKey] ?? [];
    const supplement = {
      attachments,
      content,
      key: `queued-user-${Date.now()}-${queue.length}`,
    };
    const appended = appendBoundedSupplement(queue, supplement);
    if (!appended) return false;
    const next = { ...queuesRef.current, [conversationKey]: appended };
    queuesRef.current = next;
    setQueues(next);
    return true;
  }, []);
  const peek = useCallback(
    (conversationKey: string) => queuesRef.current[conversationKey]?.[0] ?? null,
    [],
  );
  const shift = useCallback((conversationKey: string) => {
    const next = {
      ...queuesRef.current,
      [conversationKey]: (queuesRef.current[conversationKey] ?? []).slice(1),
    };
    queuesRef.current = next;
    setQueues(next);
  }, []);
  const clear = useCallback((conversationKey: string) => {
    const next = { ...queuesRef.current };
    delete next[conversationKey];
    queuesRef.current = next;
    setQueues(next);
  }, []);

  return { clear, enqueue, maxQueued: MAX_QUEUED_SUPPLEMENTS, messages, peek, shift };
}
