import { DeleteOutlined } from "@ant-design/icons";
import {
  Actions,
  Bubble,
  BubbleListProps,
  Conversations,
  Sender,
  SenderProps,
  XProvider,
} from "@ant-design/x";
import { useXConversations } from "@ant-design/x-sdk";
import XMarkdown from "@ant-design/x-markdown";
import { Flex, GetRef, message } from "antd";
import { createStyles } from "antd-style";
import { clsx } from "clsx";
import dayjs from "dayjs";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "@ant-design/x-markdown/themes/light.css";
import "@ant-design/x-markdown/themes/dark.css";
import { BubbleListRef } from "@ant-design/x/es/bubble";
import { useMarkdownTheme } from "./x-markdown/demo/_utils";
import { useOperatorConfig } from "./lib/operator-config";
import { ZebraApiError, zebraApi } from "./lib/zebra-api";
import type { SessionEvent } from "./types";
import locale from "./_utils/local";

const useStyle = createStyles(({ token, css }) => {
  return {
    layout: css`
      width: 100%;
      height: 100vh;
      display: flex;
      background: ${token.colorBgContainer};
      overflow: hidden;
    `,
    side: css`
      background: ${token.colorBgLayout};
      width: 280px;
      height: 100%;
      display: flex;
      flex-direction: column;
      padding: 0 12px;
      box-sizing: border-box;
    `,
    logo: css`
      display: flex;
      align-items: center;
      justify-content: start;
      padding: 0 24px;
      box-sizing: border-box;
      gap: 8px;
      margin: 24px 0;

      span {
        font-weight: bold;
        color: ${token.colorText};
        font-size: 16px;
      }
    `,
    conversations: css`
      overflow-y: auto;
      margin-top: 12px;
      padding: 0;
      flex: 1;
      .ant-conversations-list {
        padding-inline-start: 0;
      }
    `,
    chat: css`
      height: 100%;
      width: calc(100% - 240px);
      overflow: auto;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      .ant-bubble-content-updating {
        background-image: linear-gradient(90deg, #ff6b23 0%, #af3cb8 31%, #53b6ff 89%);
        background-size: 100% 2px;
        background-repeat: no-repeat;
        background-position: bottom;
      }
    `,
    chatList: css`
      flex: 1;
      overflow-y: auto;
      margin-block-start: ${token.margin}px;
    `,
    chatSender: css`
      padding: ${token.paddingXS}px;
    `,
    startPage: css`
      display: flex;
      flex-direction: column;
      align-items: center;
      height: 100%;
    `,
    agentName: css`
      margin-block-start: 25%;
      font-size: 32px;
      margin-block-end: 38px;
      font-weight: 600;
    `,
  };
});

interface ChatBubbleMessage {
  key: string;
  role: "assistant" | "user";
  status?: "success" | "error" | "loading";
  content: string;
}

const DEFAULT_CONVERSATIONS_ITEMS = [
  {
    key: "default-0",
    label: locale.whatIsAntDesignX,
    group: locale.today,
  },
  {
    key: "default-1",
    label: locale.howToQuicklyInstallAndImportComponents,
    group: locale.today,
  },
  {
    key: "default-2",
    label: locale.newAgiHybridInterface,
    group: locale.yesterday,
  },
];

const slotConfig: SenderProps["slotConfig"] = [
  { type: "text", value: locale.slotTextStart },
  {
    type: "select",
    key: "destination",
    props: {
      defaultValue: "Zebra Agent",
      options: ["Zebra Agent", "Local Mode"],
    },
  },
  { type: "text", value: locale.slotTextEnd },
];

function readText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function toErrorMessage(error: unknown): string {
  if (error instanceof ZebraApiError && typeof error.payload === "object" && error.payload && "reason" in error.payload) {
    return `${String(error.payload.reason)} (HTTP ${error.statusCode})`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

function isAppendToTerminalError(error: unknown): boolean {
  if (!(error instanceof ZebraApiError) || typeof error.payload !== "object" || error.payload === null) {
    return false;
  }
  const payload = error.payload as { status?: unknown; reason?: unknown };
  return (
    error.statusCode === 409 &&
    payload.status === "not_appendable" &&
    payload.reason === "cannot_append_to_terminal_session"
  );
}

function streamEventsToMessages(events: SessionEvent[]): ChatBubbleMessage[] {
  return [...events]
    .sort((left, right) => left.sequence - right.sequence)
    .flatMap((event): ChatBubbleMessage[] => {
      if (event.event_type === "user_message_received") {
        const content = readText(event.payload.content);
        if (!content) {
          return [];
        }
        return [
          {
            key: event.event_id,
            role: "user",
            status: "success",
            content,
          },
        ];
      }
      if (event.event_type === "model_response_received") {
        const content = readText(event.payload.assistant_message);
        if (!content) {
          return [];
        }
        return [
          {
            key: event.event_id,
            role: "assistant",
            status: "success",
            content,
          },
        ];
      }
      return [];
    });
}

const Footer: React.FC<{
  content: string;
  status?: string;
}> = ({ content, status }) => {
  return status !== "loading" ? <div style={{ display: "flex" }}><Actions items={[{ key: "copy", actionRender: <Actions.Copy text={content} /> }]} /></div> : null;
};

const getRole = (className: string): BubbleListProps["role"] => ({
  assistant: {
    placement: "start",
    footer: (content, { status }) => <Footer content={(typeof content === "string" ? content : "") as string} status={status} />,
    contentRender: (content, { status }) => {
      const newContent = (typeof content === "string" ? content : "").replace(/\n\n/g, "<br/><br/>");
      return (
        <XMarkdown
          paragraphTag="div"
          className={className}
          streaming={{
            hasNextChunk: status === "updating",
            enableAnimation: true,
          }}
        >
          {newContent}
        </XMarkdown>
      );
    },
  },
  user: { placement: "end" },
});

const App = () => {
  const [className] = useMarkdownTheme();
  const senderRef = useRef<GetRef<typeof Sender>>(null);

  const { config, patchConfig } = useOperatorConfig();
  const api = useMemo(() => zebraApi(config), [config]);

  const { conversations, addConversation, setConversations } = useXConversations({
    defaultConversations: DEFAULT_CONVERSATIONS_ITEMS,
  });
  const [curConversation, setCurConversation] = useState<string>(DEFAULT_CONVERSATIONS_ITEMS[0].key);
  const [activeConversation, setActiveConversation] = useState<string>(DEFAULT_CONVERSATIONS_ITEMS[0].key);
  const [conversationToSessionId, setConversationToSessionId] = useState<Record<string, string>>({});
  const [conversationMessages, setConversationMessages] = useState<Record<string, ChatBubbleMessage[]>>({});
  const [isRequesting, setIsRequesting] = useState<boolean>(false);

  const listRef = useRef<BubbleListRef>(null);
  const messages = conversationMessages[curConversation] ?? [];

  const [messageApi, contextHolder] = message.useMessage();

  const { styles } = useStyle();

  useEffect(() => {
    if (senderRef.current) {
      senderRef.current.focus({ cursor: "end" });
    }
  }, []);

  useEffect(() => {
    if (!config.sessionId) {
      return;
    }
    setConversationToSessionId((current) => {
      if (current[curConversation]) {
        return current;
      }
      return {
        ...current,
        [curConversation]: config.sessionId,
      };
    });
  }, [config.sessionId, curConversation]);

  const syncConversationFromStream = useCallback(
    async (conversationKey: string, sessionId: string) => {
      const response = await api.stream(sessionId);
      const nextMessages = streamEventsToMessages(response.events);
      setConversationMessages((current) => ({
        ...current,
        [conversationKey]: nextMessages,
      }));
    },
    [api],
  );

  useEffect(() => {
    const sessionId = conversationToSessionId[curConversation];
    if (!sessionId) {
      setConversationMessages((current) => {
        if (current[curConversation]?.length) {
          return current;
        }
        return {
          ...current,
          [curConversation]: [],
        };
      });
      return;
    }
    void syncConversationFromStream(curConversation, sessionId).catch((error: unknown) => {
      messageApi.error(toErrorMessage(error));
    });
  }, [curConversation, conversationToSessionId, syncConversationFromStream, messageApi]);

  const appendMessageToConversation = useCallback((conversationKey: string, message: ChatBubbleMessage) => {
    setConversationMessages((current) => {
      const next = [...(current[conversationKey] ?? []), message];
      return {
        ...current,
        [conversationKey]: next,
      };
    });
  }, []);

  const submitMessage = useCallback(
    async (input: string) => {
      const trimmed = input.trim();
      if (!trimmed) {
        return;
      }

      const localMessage: ChatBubbleMessage = {
        key: `local-user-${Date.now()}`,
        role: "user",
        status: "success",
        content: trimmed,
      };
      appendMessageToConversation(curConversation, localMessage);
      setIsRequesting(true);
      senderRef.current?.clear?.();
      setActiveConversation(curConversation);

      try {
        let sessionId = conversationToSessionId[curConversation];
        if (!sessionId) {
          const title = trimmed.slice(0, 48) || locale.agentName;
          const created = await api.createSession({ title, prompt: trimmed, execute: true });
          sessionId = created.session_id;
          patchConfig({ sessionId });
          setConversationToSessionId((current) => ({
            ...current,
            [curConversation]: sessionId,
          }));
          if (!created.assistant_message) {
            appendMessageToConversation(curConversation, {
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

            const title = trimmed.slice(0, 48) || locale.agentName;
            const created = await api.createSession({
              title,
              prompt: trimmed,
              execute: true,
            });
            sessionId = created.session_id;
            patchConfig({ sessionId });
            setConversationToSessionId((current) => ({
              ...current,
              [curConversation]: sessionId,
            }));
            if (!created.assistant_message) {
              appendMessageToConversation(curConversation, {
                key: `local-assistant-${Date.now()}`,
                role: "assistant",
                status: "loading",
                content: locale.noData,
              });
            }
            await syncConversationFromStream(curConversation, sessionId);
            return;
          }
        }

        await syncConversationFromStream(curConversation, sessionId);
      } catch (error: unknown) {
        messageApi.error(toErrorMessage(error));
      } finally {
        setIsRequesting(false);
        listRef.current?.scrollTo({ top: "bottom" });
      }
    },
    [appendMessageToConversation, api, conversationToSessionId, curConversation, messageApi, patchConfig, syncConversationFromStream],
  );

  return (
    <XProvider locale={locale as any}>
      {contextHolder}
      <div className={styles.layout}>
        <div className={styles.side}>
          <div className={styles.logo}>
            <img
              src="https://mdn.alipayobjects.com/huamei_iwk9zp/afts/img/A*eco6RrQhxbMAAAAAAAAAAAAADgCCAQ/original"
              draggable={false}
              alt="logo"
              width={24}
              height={24}
            />
            <span>Ant Design X</span>
          </div>
          <Conversations
            creation={{
              onClick: () => {
                const now = dayjs().valueOf().toString();
                addConversation({
                  key: now,
                  label: `${locale.newConversation} ${conversations.length + 1}`,
                  group: locale.today,
                });
                setCurConversation(now);
                setActiveConversation(now);
              },
            }}
            items={conversations
              .map((item: { key: string; label?: string; group?: string }) => ({
                ...item,
                label: item.key === activeConversation
                  ? `[${locale.curConversation}]${item.label ?? ""}`
                  : item.label ?? "",
              }))
              .sort((left: { key: string }, right: { key: string }) =>
                left.key === activeConversation ? -1 : right.key === activeConversation ? 1 : 0,
              )}
            className={styles.conversations}
            activeKey={curConversation}
            onActiveChange={(val) => {
              setCurConversation(val);
              setActiveConversation(val);
            }}
            groupable
            styles={{ item: { padding: "0 8px" } }}
            menu={(conversation: { key: string }) => ({
              items: [
                {
                  label: locale.delete,
                  key: "delete",
                  icon: <DeleteOutlined />,
                  danger: true,
                  onClick: () => {
                    const newList = conversations.filter((item: { key: string }) => item.key !== conversation.key);
                    const newConversations = newList;
                    setConversations(newConversations);
                    setConversationToSessionId((current) => {
                      const next = { ...current };
                      delete next[conversation.key];
                      return next;
                    });
                    setConversationMessages((current) => {
                      const next = { ...current };
                      delete next[conversation.key];
                      return next;
                    });
                    if (conversation.key === curConversation) {
                      setCurConversation(newConversations[0]?.key ?? "");
                      setActiveConversation(newConversations[0]?.key ?? "");
                    }
                  },
                },
              ],
            })}
          />
        </div>
        <div className={styles.chat}>
          <div className={styles.chatList}>
            {messages.length !== 0 && (
              <Bubble.List
                ref={listRef}
                styles={{
                  root: {
                    maxWidth: 940,
                    marginBlockEnd: 24,
                  },
                }}
                items={messages.map((item) => ({
                  ...item,
                  key: item.key,
                  role: item.role,
                  status: item.status,
                }))}
                role={getRole(className)}
              />
            )}
          </div>
          <div className={clsx(styles.chatSender, { [styles.startPage]: messages.length === 0 })}>
            {messages.length === 0 && <div className={styles.agentName}>{locale.agentName}</div>}
            <Sender
              suffix={false}
              ref={senderRef}
              key={curConversation}
              slotConfig={slotConfig}
              loading={isRequesting}
              onSubmit={(val) => {
                void submitMessage(val);
              }}
              onCancel={() => {
                messageApi.info("当前不支持中断请求");
              }}
              placeholder={locale.placeholder}
              footer={(actionNode) => {
                return (
                  <Flex justify="space-between" align="center">
                    <Flex gap="small" align="center" />
                    <Flex align="center">{actionNode}</Flex>
                  </Flex>
                );
              }}
              autoSize={{ minRows: 3, maxRows: 6 }}
            />
          </div>
        </div>
      </div>
    </XProvider>
  );
};

export default App;
