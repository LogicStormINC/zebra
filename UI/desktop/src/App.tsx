import { GetRef, message } from "antd";
import { Sender } from "@ant-design/x";
import { useQuery } from "@tanstack/react-query";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CodexWorkspace } from "./components/CodexWorkspace";
import locale from "./_utils/local";
import type { ChatMessage } from "./lib/chat-surface";
import { isAppendToTerminalError, streamEventsToMessages, toErrorMessage } from "./lib/chat-surface";
import { buildClarificationResponsePayload } from "./lib/clarification-continuation";
import { useOperatorConfig } from "./lib/operator-config";
import { mergeSessionEvents, pollWhile } from "./lib/live-session";
import { projectRuntimeConnection } from "./lib/runtime-connection";
import type { TaskLaunchConfig } from "./lib/task-launch-config";
import type { TextAttachmentPayload } from "./lib/text-attachments";
import { useWorkspaceSessionIndex } from "./lib/use-workspace-session-index";
import { useWorkspaceSelection } from "./lib/use-workspace-selection";
import { useActiveApproval } from "./lib/use-active-approval";
import { zebraApi } from "./lib/zebra-api";
import type { SessionEvent, SessionSummary } from "./types";
const WORKSPACE_HOME_KEY = "__workspace-home__";

export default function App() {
  const senderRef = useRef<GetRef<typeof Sender>>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const { config, patchConfig, resetConfig } = useOperatorConfig();
  const api = useMemo(() => zebraApi(config), [config]);
  const healthQuery = useQuery({
    queryKey: ["runtime-health", config.apiBaseUrl],
    queryFn: api.health,
    retry: false,
    refetchInterval: 5_000,
  });
  const runtimeStatus = projectRuntimeConnection(healthQuery.data?.status, healthQuery.data?.service, healthQuery.isFetching);
  const mcpCapabilitiesQuery = useQuery({
    queryKey: ["mcp-capabilities", config.apiBaseUrl, config.authToken],
    queryFn: api.mcpCapabilities,
    enabled: runtimeStatus === "connected",
    retry: false,
    staleTime: Infinity,
  });
  const {
    conversations,
    createIndexedConversation,
    hiddenSessionCount,
    removeIndexedConversation,
    renameConversation,
    restoreHiddenSessions,
    sessionIds: conversationToSessionId,
    sessionSummaries,
    setSessionIds: setConversationToSessionId,
    setSessionSummaries,
  } = useWorkspaceSessionIndex(api, config.sessionId.trim());
  const [currentConversation, setCurrentConversation] = useWorkspaceSelection(conversations, WORKSPACE_HOME_KEY);
  const [conversationEvents, setConversationEvents] = useState<Record<string, SessionEvent[]>>({});
  const [conversationMessages, setConversationMessages] = useState<Record<string, ChatMessage[]>>({});
  const [isRequesting, setIsRequesting] = useState(false);
  const [controlsBusy, setControlsBusy] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();
  const events = conversationEvents[currentConversation] ?? [];
  const messages = conversationMessages[currentConversation] ?? [];
  const activeConversation = conversations.find((item) => item.key === currentConversation);
  const activeLabel = activeConversation?.label ?? locale.agentName;
  const currentSessionId =
    currentConversation === WORKSPACE_HOME_KEY ? undefined : conversationToSessionId[currentConversation];
  const sessionSummary = sessionSummaries[currentConversation] ?? null;
  const isWorkspaceIdle = currentConversation === WORKSPACE_HOME_KEY;
  useEffect(() => {
    senderRef.current?.focus({ cursor: "end" });
  }, []);

  const syncConversationFromStream = useCallback(
    async (conversationKey: string, sessionId: string) => {
      const applyEvents = (incoming: SessionEvent[]) => setConversationEvents((current) => {
        return { ...current, [conversationKey]: mergeSessionEvents(current[conversationKey] ?? [], incoming) };
      });
      const applyMessages = (incoming: SessionEvent[]) => setConversationMessages((current) => {
        const messages = new Map((current[conversationKey] ?? []).map((message) => [message.key, message]));
        streamEventsToMessages(incoming).forEach((message) => messages.set(message.key, message));
        return { ...current, [conversationKey]: [...messages.values()] };
      });
      const apply = (incoming: SessionEvent[]) => { applyEvents(incoming); applyMessages(incoming); };
      const response = await api.stream(sessionId, (event) => apply([event]));
      applyEvents(response.events);
      setConversationMessages((current) => ({ ...current, [conversationKey]: streamEventsToMessages(response.events) }));
    },
    [api],
  );

  const loadSessionSummary = useCallback(
    async (conversationKey: string, sessionId: string) => {
      try {
        const summary = await api.session(sessionId);
        setSessionSummaries((current) => ({ ...current, [conversationKey]: summary }));
        return summary;
      } catch {
        setSessionSummaries((current) => ({ ...current, [conversationKey]: null }));
        return null;
      }
    },
    [api, setSessionSummaries],
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
      ]);
    },
    [conversationToSessionId, loadSessionSummary, syncConversationFromStream],
  );

  const refreshCurrentConversation = useCallback(
    () => refreshConversation(currentConversation),
    [currentConversation, refreshConversation],
  );
  const activeApproval = useActiveApproval(api, currentSessionId, sessionSummary?.status, refreshCurrentConversation);

  const executeSession = useCallback(
    async (conversationKey: string, sessionId: string) => {
      await pollWhile(api.resume(sessionId), () => Promise.all([
        syncConversationFromStream(conversationKey, sessionId),
        loadSessionSummary(conversationKey, sessionId),
      ]));
    },
    [api, loadSessionSummary, syncConversationFromStream],
  );

  const respondToClarification = useCallback(
    async (clarificationId: string, content: string) => {
      if (!currentSessionId) return;
      setControlsBusy(true);
      try {
        await api.appendMessage(
          currentSessionId,
          buildClarificationResponsePayload(clarificationId, content),
        );
        await executeSession(currentConversation, currentSessionId);
      } catch (error: unknown) {
        messageApi.error(toErrorMessage(error));
        throw error;
      } finally {
        setControlsBusy(false);
      }
    },
    [api, currentConversation, currentSessionId, executeSession, messageApi],
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
    setCurrentConversation(WORKSPACE_HOME_KEY);
  }, []);

  const deleteConversation = useCallback(
    (conversationKey: string) => {
      const sessionId = conversationToSessionId[conversationKey];
      removeIndexedConversation(conversationKey);
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
      if (sessionId && sessionId === config.sessionId) patchConfig({ sessionId: "" });
      if (conversationKey !== currentConversation) {
        return;
      }
      setCurrentConversation(WORKSPACE_HOME_KEY);
    },
    [config.sessionId, conversationToSessionId, currentConversation, patchConfig, removeIndexedConversation],
  );

  const submitMessage = useCallback(
    async (input: string, launchConfig: TaskLaunchConfig, attachments: TextAttachmentPayload[]) => {
      const trimmed = input.trim();
      if (!trimmed || !currentConversation) {
        return false;
      }
      let conversationKey = currentConversation;
      let createdFromWorkspaceHome = false;
      if (conversationKey === WORKSPACE_HOME_KEY) {
        conversationKey = createIndexedConversation(trimmed.slice(0, 36));
        createdFromWorkspaceHome = true;
        setCurrentConversation(conversationKey);
      }

      appendMessageToConversation(conversationKey, {
        key: `local-user-${Date.now()}`,
        role: "user",
        status: "success",
        content: trimmed,
      });
      setIsRequesting(true);
      senderRef.current?.clear?.();

      try {
        let sessionId = conversationToSessionId[conversationKey];
        if (!sessionId) {
          const title = trimmed.slice(0, 36) || locale.newConversation;
          const created = await api.createSession({ title, prompt: trimmed, workspace: launchConfig.workspace.trim(), execute: false, policy_profile: launchConfig.policyProfile, tool_profile: launchConfig.toolProfile, network_profile: launchConfig.networkProfile, network_allowlist: launchConfig.networkAllowlist, mcp_allowlist: launchConfig.mcpAllowlist, attachments });
          sessionId = created.session_id;
          patchConfig({ sessionId });
          if (!createdFromWorkspaceHome) {
            renameConversation(conversationKey, title);
          }
          setConversationToSessionId((current) => ({
            ...current,
            [conversationKey]: sessionId!,
          }));
          if (!created.assistant_message) {
            appendMessageToConversation(conversationKey, {
              key: `local-assistant-${Date.now()}`,
              role: "assistant",
              status: "loading",
              content: locale.noData,
            });
          }
        } else {
          try {
            await api.appendMessage(sessionId, { content: trimmed, attachments });
          } catch (error: unknown) {
            if (!isAppendToTerminalError(error)) {
              throw error;
            }
            const title = trimmed.slice(0, 36) || locale.newConversation;
            const created = await api.createSession({ title, prompt: trimmed, workspace: launchConfig.workspace.trim(), execute: false, policy_profile: launchConfig.policyProfile, tool_profile: launchConfig.toolProfile, network_profile: launchConfig.networkProfile, network_allowlist: launchConfig.networkAllowlist, mcp_allowlist: launchConfig.mcpAllowlist, attachments });
            sessionId = created.session_id;
            patchConfig({ sessionId });
            if (!createdFromWorkspaceHome) {
              renameConversation(conversationKey, title);
            }
            setConversationToSessionId((current) => ({
              ...current,
              [conversationKey]: sessionId!,
            }));
            if (!created.assistant_message) {
              appendMessageToConversation(conversationKey, {
                key: `local-assistant-${Date.now()}`,
                role: "assistant",
                status: "loading",
                content: locale.noData,
              });
            }
          }
        }
        await executeSession(conversationKey, sessionId);
        return true;
      } catch (error: unknown) {
        messageApi.error(toErrorMessage(error));
        return false;
      } finally {
        setIsRequesting(false);
      }
    },
    [
      api,
      appendMessageToConversation,
      conversationToSessionId,
      currentConversation,
      createIndexedConversation,
      executeSession,
      messageApi,
      patchConfig,
      renameConversation,
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
    void runControlAction(() => executeSession(currentConversation, sessionId));
  }, [currentConversation, currentSessionId, executeSession, runControlAction]);

  const cancelSession = useCallback(() => {
    const sessionId = currentSessionId;
    if (!sessionId) {
      return;
    }
    void runControlAction(() => api.cancel(sessionId));
  }, [api.cancel, currentSessionId, runControlAction]);

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
        conversations={conversations}
        currentConversation={currentConversation}
        currentSessionId={currentSessionId}
        events={events}
        isRequesting={isRequesting}
        listRef={listRef}
        messages={messages}
        mcpCapabilities={mcpCapabilitiesQuery.data}
        mcpCapabilitiesBusy={mcpCapabilitiesQuery.isFetching}
        mcpCapabilitiesError={mcpCapabilitiesQuery.error ? toErrorMessage(mcpCapabilitiesQuery.error) : null}
        operatorConfig={config}
        activeApproval={activeApproval.approval}
        approvalBusy={activeApproval.busy}
        approvalErrorText={activeApproval.errorText}
        clarificationBusy={controlsBusy}
        onApprove={activeApproval.approve}
        onCancel={cancelSession}
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
        onPatchConfig={patchConfig}
        onResetConfig={resetConfig}
        onRetryRuntime={() => {
          void healthQuery.refetch();
        }}
        onRetryMcpCapabilities={() => {
          void mcpCapabilitiesQuery.refetch();
        }}
        onCreateConversation={createConversation}
        onDeleteConversation={deleteConversation}
        onRestoreHiddenSessions={() => void restoreHiddenSessions().catch((error: unknown) => messageApi.error(toErrorMessage(error)))}
        hiddenSessionCount={hiddenSessionCount}
        isWorkspaceIdle={isWorkspaceIdle}
        sessionIds={conversationToSessionId}
        onCancelSession={cancelSession}
        onResumeSession={resumeSession}
        onSuspendSession={suspendSession}
        onReject={activeApproval.reject}
        onRespondClarification={respondToClarification}
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
        onSubmit={submitMessage}
        controlsBusy={controlsBusy}
        runtimeStatus={runtimeStatus}
        sessionSummaries={sessionSummaries}
        sessionSummary={sessionSummary}
        senderRef={senderRef}
      />
    </>
  );
}
