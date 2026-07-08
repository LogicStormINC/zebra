import {
  ArrowDownOutlined,
  CopyOutlined,
  EllipsisOutlined,
  FileTextOutlined,
  PauseCircleOutlined,
  PlusOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Sender } from "@ant-design/x";
import { Button, Dropdown, Flex, GetRef } from "antd";
import React from "react";
import locale from "../_utils/local";
import type { ChatMessage, ConversationSeed } from "../lib/chat-surface";
import type { SessionResultSurface } from "../lib/session-results";
import type { SessionArtifactDetailResponse, SessionEvent, SessionSummary } from "../types";
import { AssistantMessageBlock } from "./AssistantMessageBlock";
import { ArtifactDetailDrawer } from "./ArtifactDetailDrawer";
import { SessionExecutionTrace } from "./SessionExecutionTrace";
import { SessionContextCard } from "./SessionContextCard";
import { SessionResultWorkbench } from "./SessionResultWorkbench";
import { useConversationPaneStyle } from "./CodexConversationPane.styles";


interface CodexConversationPaneProps {
  activeLabel: string;
  apiBaseUrl: string;
  artifactContentPreview: string | null;
  artifactDetail: SessionArtifactDetailResponse | null;
  artifactLoading: boolean;
  currentConversation: string;
  currentSessionId?: string;
  conversations: ConversationSeed[];
  conversationSessionIds: Record<string, string>;
  events: SessionEvent[];
  isRequesting: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
  messages: ChatMessage[];
  onCancel: () => void;
  onCloseArtifact: () => void;
  onCopySessionId: () => void;
  onCopyWorkspacePath: () => void;
  onCreateConversation: () => void;
  onCancelSession: () => void;
  onResumeSession: () => void;
  onSuspendSession: () => void;
  onOpenArtifact: (artifactId: string) => void;
  onRefreshConversation: () => void;
  onScrollToLatest: () => void;
  onSelectConversation: (key: string) => void;
  onSubmit: (value: string) => void;
  controlsBusy: boolean;
  resultSurface: SessionResultSurface | null;
  sessionSummaries: Record<string, SessionSummary | null>;
  sessionSummary: SessionSummary | null;
  senderRef: React.RefObject<GetRef<typeof Sender> | null>;
}

export function CodexConversationPane({
  activeLabel,
  apiBaseUrl,
  artifactContentPreview,
  artifactDetail,
  artifactLoading,
  currentConversation,
  currentSessionId,
  conversations,
  conversationSessionIds,
  events,
  isRequesting,
  listRef,
  messages,
  onCancel,
  onCloseArtifact,
  onCopySessionId,
  onCopyWorkspacePath,
  onCreateConversation,
  onCancelSession,
  onResumeSession,
  onSuspendSession,
  onOpenArtifact,
  onRefreshConversation,
  onScrollToLatest,
  onSelectConversation,
  onSubmit,
  controlsBusy,
  resultSurface,
  sessionSummaries,
  sessionSummary,
  senderRef,
}: CodexConversationPaneProps) {
  const { styles } = useConversationPaneStyle();
  const [composerValue, setComposerValue] = React.useState("");
  const canSubmit = composerValue.trim().length > 0;
  const hasThread = Boolean(currentSessionId) || messages.length > 0 || events.length > 0;
  const headerTitle = hasThread ? activeLabel : locale.idleProjectName;
  const headerMeta = hasThread
    ? currentSessionId
      ? `${sessionSummary?.workspace?.policy_profile ?? locale.accessWorkspaceWrite} · ${currentSessionId.slice(0, 8)}`
      : locale.idleState
    : locale.idleState;
  const suggestedActions = [
    { label: locale.hintDocs, prompt: "阅读项目文档，并总结当前主线开发状态。" },
    { label: locale.hintExplain, prompt: "解释当前项目结构和核心模块职责。" },
    { label: locale.hintDebug, prompt: "定位当前项目里最需要修复的一个问题，并给出实现方案。" },
    { label: locale.hintImplement, prompt: "基于当前项目状态，继续实现下一个最小功能切片。" },
    { label: locale.hintShip, prompt: "为当前实现补充必要测试，并运行验证命令。" },
  ];
  const recentThreads = conversations.filter((item) => item.key !== currentConversation).slice(0, 5);
  const statusLabel = (status: string | undefined) => {
    if (status === "running") return locale.statusRunning;
    if (status === "waiting_approval" || status === "waiting_user") return locale.statusWaiting;
    if (status === "completed") return locale.statusDone;
    if (status === "failed") return locale.statusFailed;
    if (status === "review") return locale.statusReview;
    return locale.statusDraft;
  };
  const renderComposer = (variant: "idle" | "thread") => (
    <div className={variant === "idle" ? styles.idleComposerCard : styles.composerCard}>
      <div className={styles.sender}>
        <Sender
          autoSize={variant === "idle" ? { minRows: 2, maxRows: 6 } : { minRows: 2, maxRows: 3 }}
          footer={(actionNode) => (
            <Flex align="center" className={styles.composerFooter} justify="space-between">
              <Flex align="center" className={styles.composerTools} gap={8}>
                <span className={styles.modeSegment}>
                  <span className={styles.modePill}>{locale.modeAsk}</span>
                  <span className={styles.modePillActive}>{locale.modeAct}</span>
                </span>
                <button className={styles.toolbarButton} type="button">{locale.attach}</button>
                <button className={styles.toolbarButton} type="button">{locale.accessWorkspaceWrite}</button>
                <button className={styles.toolbarButton} type="button">{locale.modelDeepSeek}</button>
              </Flex>
              <span className={`${styles.sendSlot} ${canSubmit ? "" : styles.sendSlotDisabled}`}>
                {actionNode}
              </span>
            </Flex>
          )}
          key={`${variant}-${currentConversation}`}
          loading={isRequesting}
          onCancel={onCancel}
          onChange={(value) => {
            setComposerValue(value);
          }}
          onSubmit={(value) => {
            const trimmed = value.trim();
            if (!trimmed) {
              return;
            }
            onSubmit(trimmed);
            setComposerValue("");
          }}
          placeholder={locale.placeholder}
          ref={senderRef}
          suffix={false}
          value={composerValue}
        />
      </div>
    </div>
  );
  const workspaceMenuItems = [
    {
      key: "copy-workspace",
      icon: <FolderOpenOutlined />,
      label: locale.copyWorkspacePath,
      onClick: onCopyWorkspacePath,
      disabled: !sessionSummary?.workspace?.workspace_root,
    },
    {
      key: "copy-session",
      icon: <CopyOutlined />,
      label: locale.copySessionId,
      onClick: onCopySessionId,
      disabled: !currentSessionId,
    },
    {
      key: "refresh-session",
      icon: <ReloadOutlined />,
      label: locale.refreshConversation,
      onClick: onRefreshConversation,
      disabled: !currentSessionId,
    },
  ];
  const sessionMenuItems = [
    {
      key: "new-conversation",
      icon: <PlusOutlined />,
      label: locale.newConversation,
      onClick: onCreateConversation,
    },
    {
      key: "suspend-session",
      icon: <PauseCircleOutlined />,
      label: locale.suspendSession,
      onClick: onSuspendSession,
      disabled: !currentSessionId || controlsBusy,
    },
    {
      key: "resume-session",
      icon: <PlayCircleOutlined />,
      label: locale.resumeSession,
      onClick: onResumeSession,
      disabled: !currentSessionId || controlsBusy,
    },
    {
      key: "cancel-session",
      icon: <StopOutlined />,
      label: locale.cancelSession,
      onClick: onCancelSession,
      disabled: !currentSessionId || controlsBusy,
    },
    {
      key: "scroll-latest",
      icon: <ArrowDownOutlined />,
      label: locale.scrollToLatest,
      onClick: onScrollToLatest,
      disabled: messages.length === 0,
    },
    {
      key: "copy-session",
      icon: <CopyOutlined />,
      label: locale.copySessionId,
      onClick: onCopySessionId,
      disabled: !currentSessionId,
    },
    {
      key: "close-artifact",
      icon: <FileTextOutlined />,
      label: locale.closeArtifactPanel,
      onClick: onCloseArtifact,
      disabled: !artifactDetail && !artifactLoading,
    },
  ];

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div className={styles.titleWrap}>
          <span className={styles.titleIcon}>
            <FileTextOutlined />
          </span>
          <div className={styles.titleBlock}>
            <h1>{headerTitle}</h1>
            <span className={styles.titleMeta}>{headerMeta}</span>
          </div>
        </div>
        <div className={styles.headerActions}>
          <Dropdown menu={{ items: workspaceMenuItems }} trigger={["click"]}>
            <Button className={styles.workspaceBadge} icon={<FolderOpenOutlined />} type="default">
              {locale.workspaceBadge}
            </Button>
          </Dropdown>
          <Button
            className={styles.actionButton}
            icon={<ReloadOutlined />}
            onClick={onRefreshConversation}
            type="default"
          />
          <Dropdown menu={{ items: sessionMenuItems }} trigger={["click"]}>
            <Button className={styles.actionButton} icon={<EllipsisOutlined />} type="default" />
          </Dropdown>
        </div>
      </header>

      <div className={styles.center}>
        <div className={styles.stream} ref={listRef}>
          <div className={styles.streamInner}>
            {!hasThread ? (
              <div className={styles.idleWorkspace}>
                <h2 className={styles.idleQuestion}>{locale.idlePromptTitle}</h2>
                <div className={styles.idleSubtitle}>{locale.idlePromptSubtitle}</div>
                {renderComposer("idle")}
                <section className={styles.idleSection}>
                  <div className={styles.idleSectionTitle}>{locale.suggestedActions}</div>
                  <div className={styles.actionGrid}>
                    {suggestedActions.map((action) => (
                      <button
                        className={styles.quickAction}
                        key={action.label}
                        onClick={() => onSubmit(action.prompt)}
                        type="button"
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                </section>
                <section className={styles.idleSection}>
                  <div className={styles.idleSectionTitle}>{locale.recentThreads}</div>
                  <div className={styles.recentGroup}>{locale.todayGroup}</div>
                  <div className={styles.recentList}>
                    {recentThreads.map((item) => (
                      <button
                        className={styles.recentThread}
                        key={item.key}
                        onClick={() => onSelectConversation(item.key)}
                        type="button"
                      >
                        <span>{item.label}</span>
                        <span>
                          {statusLabel(sessionSummaries[item.key]?.status)} · {item.group === locale.pinned ? locale.todayGroup : item.group} · {locale.accessWorkspaceWrite.replace("权限: ", "")}
                        </span>
                      </button>
                    ))}
                    {recentThreads.length === 0 ? (
                      <div className={styles.recentEmpty}>{locale.noRecentSessions}</div>
                    ) : null}
                  </div>
                </section>
              </div>
            ) : (
              <>
                {sessionSummary ? <SessionContextCard apiBaseUrl={apiBaseUrl} session={sessionSummary} /> : null}
                <SessionResultWorkbench
                  artifactContentPreview={artifactContentPreview}
                  artifactDetail={artifactDetail}
                  onSelectArtifact={onOpenArtifact}
                  surface={resultSurface}
                />
                <SessionExecutionTrace events={events} />
                <div className={styles.messageStack}>
                  {messages.map((item) =>
                    item.role === "assistant" ? (
                      <AssistantMessageBlock key={item.key} message={item} />
                    ) : (
                      <div className={styles.userWrap} key={item.key}>
                        <div className={styles.userCard}>{item.content}</div>
                      </div>
                    ),
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {hasThread ? <div className={styles.composerDock}>{renderComposer("thread")}</div> : null}
      </div>
      <ArtifactDetailDrawer
        contentPreview={artifactContentPreview}
        detail={artifactDetail}
        loading={artifactLoading}
        onClose={onCloseArtifact}
        open={artifactLoading || artifactDetail !== null}
      />
    </main>
  );
}
