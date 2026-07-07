import { GetRef, message } from "antd";
import dayjs from "dayjs";
import { Sender } from "@ant-design/x";
import { useXConversations } from "@ant-design/x-sdk";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CodexWorkspace } from "./components/CodexWorkspace";
import locale from "./_utils/local";
import type { ChatMessage, ConversationSeed } from "./lib/chat-surface";
import {
  DEFAULT_CONVERSATIONS,
  isAppendToTerminalError,
  streamEventsToMessages,
  toErrorMessage,
} from "./lib/chat-surface";
import { useOperatorConfig } from "./lib/operator-config";
import type { SessionResultSurface } from "./lib/session-results";
import { zebraApi } from "./lib/zebra-api";
import type { SessionArtifactDetailResponse, SessionEvent, SessionSummary } from "./types";

function buildConversation(label: string, group: string): ConversationSeed {
  return {
    key: Date.now().toString(),
    label,
    group,
  };
}

function buildEmptyConversation(): ConversationSeed {
  return buildConversation(locale.newConversation, locale.today);
}

function decodeArtifactContent(contentBase64: string) {
  const binary = window.atob(contentBase64);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

export default function App() {
  const senderRef = useRef<GetRef<typeof Sender>>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const { config, patchConfig } = useOperatorConfig();
  const api = useMemo(() => zebraApi(config), [config]);

  const { conversations, addConversation, setConversations } = useXConversations({
    defaultConversations: DEFAULT_CONVERSATIONS,
  });
  const [currentConversation, setCurrentConversation] = useState<string>(DEFAULT_CONVERSATIONS[0].key);
  const [conversationToSessionId, setConversationToSessionId] = useState<Record<string, string>>({});
  const [conversationEvents, setConversationEvents] = useState<Record<string, SessionEvent[]>>({});
  const [conversationMessages, setConversationMessages] = useState<Record<string, ChatMessage[]>>({});
  const [resultSurfaces, setResultSurfaces] = useState<Record<string, SessionResultSurface | null>>({});
  const [sessionSummaries, setSessionSummaries] = useState<Record<string, SessionSummary | null>>({});
  const [artifactContentPreview, setArtifactContentPreview] = useState<string | null>(null);
  const [artifactDetail, setArtifactDetail] = useState<SessionArtifactDetailResponse | null>(null);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [isRequesting, setIsRequesting] = useState(false);
  const [controlsBusy, setControlsBusy] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  const events = conversationEvents[currentConversation] ?? [];
  const messages = conversationMessages[currentConversation] ?? [];
  const activeConversation = conversations.find((item) => item.key === currentConversation);
  const activeLabel = activeConversation?.label ?? locale.agentName;
  const currentSessionId = conversationToSessionId[currentConversation] ?? config.sessionId;
  const resultSurface = resultSurfaces[currentConversation] ?? null;
  const sessionSummary = sessionSummaries[currentConversation] ?? null;

  useEffect(() => {
    senderRef.current?.focus({ cursor: "end" });
  }, []);

  useEffect(() => {
    if (!config.sessionId || !currentConversation) {
      return;
    }
    setConversationToSessionId((current) => {
      if (current[currentConversation]) {
        return current;
      }
      return {
        ...current,
        [currentConversation]: config.sessionId,
      };
    });
  }, [config.sessionId, currentConversation]);

  const syncConversationFromStream = useCallback(
    async (conversationKey: string, sessionId: string) => {
      const response = await api.stream(sessionId);
      const nextMessages = streamEventsToMessages(response.events);
      setConversationEvents((current) => ({
        ...current,
        [conversationKey]: response.events,
      }));
      setConversationMessages((current) => ({
        ...current,
        [conversationKey]: nextMessages,
      }));
    },
    [api],
  );

  const loadSessionSummary = useCallback(
    async (conversationKey: string, sessionId: string) => {
      try {
        const summary = await api.session(sessionId);
        setSessionSummaries((current) => ({
          ...current,
          [conversationKey]: summary,
        }));
        return summary;
      } catch {
        setSessionSummaries((current) => ({
          ...current,
          [conversationKey]: null,
        }));
        return null;
      }
    },
    [api],
  );

  const loadResultSurface = useCallback(
    async (conversationKey: string, sessionId: string) => {
      const [diffResult, artifactResult, deliveryAuditResult] = await Promise.allSettled([
        api.diff(sessionId),
        api.artifacts(sessionId),
        api.deliveryAudit(sessionId),
      ]);
      setResultSurfaces((current) => ({
        ...current,
        [conversationKey]: {
          diff: diffResult.status === "fulfilled" ? diffResult.value : null,
          artifacts: artifactResult.status === "fulfilled" ? artifactResult.value : null,
          deliveryAudit: deliveryAuditResult.status === "fulfilled" ? deliveryAuditResult.value : null,
        },
      }));
    },
    [api],
  );

  const refreshConversation = useCallback(
    async (conversationKey: string) => {
      const sessionId = conversationToSessionId[conversationKey];
      if (!sessionId) {
        return;
      }
      await Promise.all([
        syncConversationFromStream(conversationKey, sessionId),
        loadSessionSummary(conversationKey, sessionId),
        loadResultSurface(conversationKey, sessionId),
      ]);
    },
    [conversationToSessionId, loadResultSurface, loadSessionSummary, syncConversationFromStream],
  );

  const runControlAction = useCallback(
    async (handler: () => Promise<unknown>) => {
      setControlsBusy(true);
      try {
        await handler();
        if (currentConversation) {
          await refreshConversation(currentConversation);
        }
      } catch (error: unknown) {
        messageApi.error(toErrorMessage(error));
      } finally {
        setControlsBusy(false);
      }
    },
    [currentConversation, messageApi, refreshConversation],
  );

  useEffect(() => {
    if (!currentConversation) {
      return;
    }
    const sessionId = conversationToSessionId[currentConversation];
    if (!sessionId) {
      setConversationMessages((current) => {
        if (current[currentConversation]) {
          return current;
        }
        return {
          ...current,
          [currentConversation]: [],
        };
      });
      setConversationEvents((current) => ({
        ...current,
        [currentConversation]: [],
      }));
      return;
    }
    void syncConversationFromStream(currentConversation, sessionId).catch((error: unknown) => {
      messageApi.error(toErrorMessage(error));
    });
  }, [currentConversation, conversationToSessionId, messageApi, syncConversationFromStream]);

  useEffect(() => {
    if (!currentConversation) {
      return;
    }
    const sessionId = conversationToSessionId[currentConversation];
    if (!sessionId) {
      setSessionSummaries((current) => {
        if (current[currentConversation] === null) {
          return current;
        }
        return {
          ...current,
          [currentConversation]: null,
        };
      });
      return;
    }
    void loadSessionSummary(currentConversation, sessionId);
  }, [conversationToSessionId, currentConversation, loadSessionSummary]);

  useEffect(() => {
    if (!currentConversation) {
      return;
    }
    const sessionId = conversationToSessionId[currentConversation];
    if (!sessionId) {
      setResultSurfaces((current) => ({
        ...current,
        [currentConversation]: null,
      }));
      return;
    }
    void loadResultSurface(currentConversation, sessionId);
  }, [conversationToSessionId, currentConversation, loadResultSurface]);

  useEffect(() => {
    if (!listRef.current) {
      return;
    }
    window.requestAnimationFrame(() => {
      if (!listRef.current) {
        return;
      }
      listRef.current.scrollTo({
        top: listRef.current.scrollHeight,
        behavior: "smooth",
      });
    });
  }, [messages.length, currentConversation]);

  const appendMessageToConversation = useCallback((conversationKey: string, nextMessage: ChatMessage) => {
    setConversationMessages((current) => ({
      ...current,
      [conversationKey]: [...(current[conversationKey] ?? []), nextMessage],
    }));
  }, []);

  const createConversation = useCallback(() => {
    const nextConversation = buildEmptyConversation();
    addConversation(nextConversation);
    setCurrentConversation(nextConversation.key);
  }, [addConversation]);

  const deleteConversation = useCallback(
    (conversationKey: string) => {
      const nextConversations = conversations.filter((item) => item.key !== conversationKey);
      setConversations(nextConversations);
      setConversationToSessionId((current) => {
        const next = { ...current };
        delete next[conversationKey];
        return next;
      });
      setConversationMessages((current) => {
        const next = { ...current };
        delete next[conversationKey];
        return next;
      });
      setConversationEvents((current) => {
        const next = { ...current };
        delete next[conversationKey];
        return next;
      });
      if (conversationKey !== currentConversation) {
        return;
      }
      if (nextConversations.length > 0) {
        setCurrentConversation(nextConversations[0].key);
        return;
      }
      const fallback = buildEmptyConversation();
      addConversation(fallback);
      setCurrentConversation(fallback.key);
    },
    [addConversation, conversations, currentConversation, setConversations],
  );

  const renameCurrentConversation = useCallback(
    (title: string) => {
      setConversations(
        conversations.map((item) =>
          item.key === currentConversation
            ? {
                ...item,
                label: title,
                group: dayjs().format("HH:mm"),
              }
            : item,
        ),
      );
    },
    [conversations, currentConversation, setConversations],
  );

  const submitMessage = useCallback(
    async (input: string) => {
      const trimmed = input.trim();
      if (!trimmed || !currentConversation) {
        return;
      }

      appendMessageToConversation(currentConversation, {
        key: `local-user-${Date.now()}`,
        role: "user",
        status: "success",
        content: trimmed,
      });
      setIsRequesting(true);
      senderRef.current?.clear?.();

      try {
        let sessionId = conversationToSessionId[currentConversation];
        if (!sessionId) {
          const title = trimmed.slice(0, 36) || locale.newConversation;
          const created = await api.createSession({ title, prompt: trimmed, execute: true });
          sessionId = created.session_id;
          patchConfig({ sessionId });
          renameCurrentConversation(title);
          setConversationToSessionId((current) => ({
            ...current,
            [currentConversation]: sessionId!,
          }));
          if (!created.assistant_message) {
            appendMessageToConversation(currentConversation, {
              key: `local-assistant-${Date.now()}`,
              role: "assistant",
              status: "loading",
              content: locale.noData,
            });
          }
        } else {
          try {
            await api.appendMessage(sessionId, { content: trimmed });
            await api.resume(sessionId);
          } catch (error: unknown) {
            if (!isAppendToTerminalError(error)) {
              throw error;
            }
            const title = trimmed.slice(0, 36) || locale.newConversation;
            const created = await api.createSession({ title, prompt: trimmed, execute: true });
            sessionId = created.session_id;
            patchConfig({ sessionId });
            renameCurrentConversation(title);
            setConversationToSessionId((current) => ({
              ...current,
              [currentConversation]: sessionId!,
            }));
            if (!created.assistant_message) {
              appendMessageToConversation(currentConversation, {
                key: `local-assistant-${Date.now()}`,
                role: "assistant",
                status: "loading",
                content: locale.noData,
              });
            }
            await syncConversationFromStream(currentConversation, sessionId);
            return;
          }
        }

        await syncConversationFromStream(currentConversation, sessionId);
      } catch (error: unknown) {
        messageApi.error(toErrorMessage(error));
      } finally {
        setIsRequesting(false);
      }
    },
    [
      api,
      appendMessageToConversation,
      conversationToSessionId,
      currentConversation,
      messageApi,
      patchConfig,
      renameCurrentConversation,
      syncConversationFromStream,
    ],
  );

  const suspendSession = useCallback(() => {
    const sessionId = currentSessionId;
    if (!sessionId) {
      return;
    }
    void runControlAction(() => api.suspend(sessionId));
  }, [api.suspend, currentSessionId, runControlAction]);

  const resumeSession = useCallback(() => {
    const sessionId = currentSessionId;
    if (!sessionId) {
      return;
    }
    void runControlAction(() => api.resume(sessionId));
  }, [api.resume, currentSessionId, runControlAction]);

  const cancelSession = useCallback(() => {
    const sessionId = currentSessionId;
    if (!sessionId) {
      return;
    }
    void runControlAction(() => api.cancel(sessionId));
  }, [api.cancel, currentSessionId, runControlAction]);

  const openArtifact = useCallback(
    async (artifactId: string) => {
      const sessionId = conversationToSessionId[currentConversation];
      if (!sessionId) {
        return;
      }
      setArtifactLoading(true);
      setArtifactDetail(null);
      setArtifactContentPreview(null);
      try {
        const detail = await api.artifactDetail(sessionId, artifactId);
        setArtifactDetail(detail);
        if (detail.artifact.retrieval.retrievable) {
          const content = await api.artifactContent(sessionId, artifactId);
          setArtifactContentPreview(decodeArtifactContent(content.content_base64));
        }
      } catch (error: unknown) {
        messageApi.error(toErrorMessage(error));
      } finally {
        setArtifactLoading(false);
      }
    },
    [api, conversationToSessionId, currentConversation, messageApi],
  );

  const copyText = useCallback(
    async (value: string, successText: string) => {
      try {
        await navigator.clipboard.writeText(value);
        messageApi.success(successText);
      } catch (error: unknown) {
        messageApi.error(toErrorMessage(error));
      }
    },
    [messageApi],
  );

  return (
    <>
      {contextHolder}
      <CodexWorkspace
        activeLabel={activeLabel}
        apiBaseUrl={config.apiBaseUrl}
        artifactContentPreview={artifactContentPreview}
        artifactDetail={artifactDetail}
        artifactLoading={artifactLoading}
        conversations={conversations as ConversationSeed[]}
        conversationSessionIds={conversationToSessionId}
        currentConversation={currentConversation}
        currentSessionId={currentSessionId}
        events={events}
        isRequesting={isRequesting}
        listRef={listRef}
        messages={messages}
        onCancel={() => {
          messageApi.info("当前不支持中断请求");
        }}
        onCloseArtifact={() => {
          setArtifactDetail(null);
          setArtifactContentPreview(null);
        }}
        onCopySessionId={() => {
          if (!currentSessionId) {
            return;
          }
          void copyText(currentSessionId, locale.sessionIdCopied);
        }}
        onCopyWorkspacePath={() => {
          const workspacePath = sessionSummary?.workspace?.workspace_root;
          if (!workspacePath) {
            return;
          }
          void copyText(workspacePath, locale.workspacePathCopied);
        }}
        onCreateConversation={createConversation}
        onDeleteConversation={deleteConversation}
        onCancelSession={cancelSession}
        onResumeSession={resumeSession}
        onSuspendSession={suspendSession}
        onOpenArtifact={(artifactId) => {
          void openArtifact(artifactId);
        }}
        onRefreshConversation={() => {
          void refreshConversation(currentConversation).catch((error: unknown) => {
            messageApi.error(toErrorMessage(error));
          });
        }}
        onScrollToLatest={() => {
          listRef.current?.scrollTo({
            top: listRef.current.scrollHeight,
            behavior: "smooth",
          });
        }}
        onSelectConversation={setCurrentConversation}
        onSubmit={(value) => {
          void submitMessage(value);
        }}
        controlsBusy={controlsBusy}
        resultSurface={resultSurface}
        sessionSummaries={sessionSummaries}
        sessionSummary={sessionSummary}
        senderRef={senderRef}
      />
    </>
  );
}
