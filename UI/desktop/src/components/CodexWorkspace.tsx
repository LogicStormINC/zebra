import { XProvider } from "@ant-design/x";
import { Drawer } from "antd";
import { createStyles } from "antd-style";
import React, { useState } from "react";
import locale from "../_utils/local";
import type { ChatMessage, ConversationSeed } from "../lib/chat-surface";
import type { SessionResultSurface } from "../lib/session-results";
import type { RuntimeConnectionStatus } from "../lib/runtime-connection";
import { projectWorkspaceLabel } from "../lib/workspace-projection";
import type { OperatorConfig, SessionArtifactDetailResponse, SessionEvent, SessionSummary } from "../types";
import { CodexConversationPane } from "./CodexConversationPane";
import { CodexSidebar } from "./CodexSidebar";
import { OperatorConfigCard } from "./OperatorConfigCard";
import type { GetRef } from "antd";
import type { Sender } from "@ant-design/x";

const useStyle = createStyles(({ css }) => {
  return {
    shell: css`
      width: 100%;
      height: 100dvh;
      min-height: 0;
      overflow: hidden;
      display: grid;
      grid-template-columns: var(--zebra-sidebar-width) minmax(0, 1fr);
      background: var(--zebra-page-background);
      color: var(--zebra-text-primary);
      @media (min-width: 1020px) {
        grid-template-columns: 280px minmax(0, 1fr);
      }
      @media (max-width: 767px) {
        --zebra-sidebar-width: 72px;
        column-gap: 0;
      }
    `,
  };
});

interface CodexWorkspaceProps {
  activeLabel: string;
  artifactContentPreview: string | null;
  artifactDetail: SessionArtifactDetailResponse | null;
  artifactLoading: boolean;
  conversations: ConversationSeed[];
  currentConversation: string;
  currentSessionId?: string;
  events: SessionEvent[];
  isWorkspaceIdle: boolean;
  isRequesting: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
  messages: ChatMessage[];
  operatorConfig: OperatorConfig;
  onCancel: () => void;
  onCloseArtifact: () => void;
  onCopySessionId: () => void;
  onCopyWorkspacePath: () => void;
  onPatchConfig: (patch: Partial<OperatorConfig>) => void;
  onResetConfig: () => void;
  onRetryRuntime: () => void;
  onCreateConversation: () => void;
  onDeleteConversation: (key: string) => void;
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
  runtimeStatus: RuntimeConnectionStatus;
  sessionSummaries: Record<string, SessionSummary | null>;
  sessionSummary: SessionSummary | null;
  senderRef: React.RefObject<GetRef<typeof Sender> | null>;
}

export function CodexWorkspace(props: CodexWorkspaceProps) {
  const { styles } = useStyle();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const runtimeLabel = props.runtimeStatus === "connected"
    ? locale.runtimeConnected
    : props.runtimeStatus === "checking"
      ? locale.runtimeChecking
      : locale.runtimeDisconnected;
  const workspaceRoot = props.sessionSummary?.workspace?.workspace_root;
  const projectMeta = workspaceRoot
    ? `${projectWorkspaceLabel(workspaceRoot, locale.workspaceUnbound)} · ${props.sessionSummary?.workspace?.status ?? locale.notBound}`
    : locale.workspaceUnbound;

  return (
    <XProvider locale={locale as any}>
      <>
        <div className={styles.shell}>
          <CodexSidebar
            conversations={props.conversations}
            currentConversation={props.currentConversation}
            isWorkspaceIdle={props.isWorkspaceIdle}
            onCreateConversation={props.onCreateConversation}
            onDeleteConversation={props.onDeleteConversation}
            onSelectConversation={props.onSelectConversation}
            projectMeta={projectMeta}
            runtimeLabel={runtimeLabel}
            sessionSummaries={props.sessionSummaries}
          />
          <CodexConversationPane
            activeLabel={props.activeLabel}
            artifactContentPreview={props.artifactContentPreview}
            artifactDetail={props.artifactDetail}
            artifactLoading={props.artifactLoading}
            conversations={props.conversations}
            controlsBusy={props.controlsBusy}
            currentConversation={props.currentConversation}
            currentSessionId={props.currentSessionId}
            events={props.events}
            isRequesting={props.isRequesting}
            isWorkspaceIdle={props.isWorkspaceIdle}
            listRef={props.listRef}
            messages={props.messages}
            onCancel={props.onCancel}
            onCancelSession={props.onCancelSession}
            onCloseArtifact={props.onCloseArtifact}
            onCopySessionId={props.onCopySessionId}
            onCopyWorkspacePath={props.onCopyWorkspacePath}
            onCreateConversation={props.onCreateConversation}
            onOpenArtifact={props.onOpenArtifact}
            onOpenSettings={() => setSettingsOpen(true)}
            onRefreshConversation={props.onRefreshConversation}
            onResumeSession={props.onResumeSession}
            onScrollToLatest={props.onScrollToLatest}
            onSelectConversation={props.onSelectConversation}
            onSubmit={props.onSubmit}
            onSuspendSession={props.onSuspendSession}
            resultSurface={props.resultSurface}
            runtimeStatus={props.runtimeStatus}
            senderRef={props.senderRef}
            sessionSummaries={props.sessionSummaries}
            sessionSummary={props.sessionSummary}
          />
        </div>
        <Drawer onClose={() => setSettingsOpen(false)} open={settingsOpen} title={locale.runtimeSettings} width={460}>
          <OperatorConfigCard
            config={props.operatorConfig}
            onChange={props.onPatchConfig}
            onReset={props.onResetConfig}
            onRetry={props.onRetryRuntime}
            runtimeStatus={props.runtimeStatus}
          />
        </Drawer>
      </>
    </XProvider>
  );
}
