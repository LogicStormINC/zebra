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
import type { ChatMessage } from "../lib/chat-surface";
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
  onSubmit: (value: string) => void;
  controlsBusy: boolean;
  resultSurface: SessionResultSurface | null;
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
  onSubmit,
  controlsBusy,
  resultSurface,
  sessionSummary,
  senderRef,
}: CodexConversationPaneProps) {
  const { styles } = useConversationPaneStyle();
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
            <h1>{activeLabel}</h1>
            <span className={styles.titleMeta}>{currentSessionId ? currentSessionId.slice(0, 8) : locale.idleState}</span>
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
            {sessionSummary ? <SessionContextCard apiBaseUrl={apiBaseUrl} session={sessionSummary} /> : null}
            <SessionResultWorkbench
              artifactContentPreview={artifactContentPreview}
              artifactDetail={artifactDetail}
              onSelectArtifact={onOpenArtifact}
              surface={resultSurface}
            />
            <SessionExecutionTrace events={events} />
            {messages.length === 0 ? (
              <div className={styles.emptyState}>
                <span className={styles.eyebrow}>{locale.emptyEyebrow}</span>
                <h2 className={styles.emptyTitle}>{locale.emptyTitle}</h2>
                <div className={styles.emptyCopy}>{locale.emptyDescription}</div>
                <div className={styles.hintRow}>
                  <span className={styles.hintChip}>{locale.hintDocs}</span>
                  <span className={styles.hintChip}>{locale.hintDebug}</span>
                  <span className={styles.hintChip}>{locale.hintShip}</span>
                </div>
              </div>
            ) : (
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
            )}
          </div>
        </div>

        <div className={styles.composerDock}>
          <div className={styles.composerCard}>
            <div className={styles.sender}>
              <Sender
                autoSize={{ minRows: 3, maxRows: 7 }}
                footer={(actionNode) => (
                  <Flex align="center" className={styles.composerFooter} justify="space-between">
                    <span className={styles.permissionTag}>
                      <span />
                      <span>{locale.permissionFullAccess}</span>
                    </span>
                    <Flex align="center" gap={16}>
                      <span className={styles.footerMeta}>{locale.modelLabel}</span>
                      {actionNode}
                    </Flex>
                  </Flex>
                )}
                key={currentConversation}
                loading={isRequesting}
                onCancel={onCancel}
                onSubmit={onSubmit}
                placeholder={locale.placeholder}
                ref={senderRef}
                suffix={false}
              />
            </div>
          </div>
        </div>
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
