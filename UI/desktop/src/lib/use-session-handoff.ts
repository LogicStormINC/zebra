import React from "react";
import type { SessionHandoffPayload, SessionHandoffResponse } from "../types";
import { handoffIdempotencyScope } from "./session-handoff";
import type { ZebraApiClient } from "./zebra-api";

interface SessionHandoffActionsInput {
  api: ZebraApiClient;
  currentSessionId?: string;
  createConversation: (title: string) => string;
  loadSummary: (conversationKey: string, sessionId: string) => Promise<unknown>;
  patchSessionId: (sessionId: string) => void;
  selectConversation: (conversationKey: string) => void;
  setBusy: (busy: boolean) => void;
  setSessionIds: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  streamSession: (conversationKey: string, sessionId: string) => Promise<unknown>;
  onError: (error: unknown) => void;
  onSuccess: (message: string) => void;
}

export function useSessionHandoffActions(input: SessionHandoffActionsInput) {
  const idempotencyKeys = React.useRef(new Map<string, string>());
  const previewHandoff = React.useCallback(
    async (payload: SessionHandoffPayload) => {
      if (!input.currentSessionId) throw new Error("No active session");
      return input.api.previewHandoff(input.currentSessionId, payload);
    },
    [input.api, input.currentSessionId],
  );
  const createHandoff = React.useCallback(
    async (payload: SessionHandoffPayload): Promise<SessionHandoffResponse> => {
      if (!input.currentSessionId) throw new Error("No active session");
      const scope = handoffIdempotencyScope(input.currentSessionId, payload);
      const idempotencyKey = idempotencyKeys.current.get(scope) ?? crypto.randomUUID();
      idempotencyKeys.current.set(scope, idempotencyKey);
      input.setBusy(true);
      try {
        const created = await input.api.createHandoff(
          input.currentSessionId,
          payload,
          idempotencyKey,
        );
        const conversationKey = input.createConversation(payload.title);
        input.setSessionIds((current) => ({
          ...current,
          [conversationKey]: created.child_session_id,
        }));
        input.patchSessionId(created.child_session_id);
        input.selectConversation(conversationKey);
        await input.loadSummary(conversationKey, created.child_session_id);
        void input.streamSession(conversationKey, created.child_session_id).catch(input.onError);
        input.onSuccess(`Stage ${created.stage_index} ready`);
        return created;
      } finally {
        input.setBusy(false);
      }
    },
    [input],
  );
  return { createHandoff, previewHandoff };
}
