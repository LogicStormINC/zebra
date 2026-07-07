import { XProvider } from "@ant-design/x";
import { createStyles } from "antd-style";
import React from "react";
import locale from "../_utils/local";
import type { ChatMessage, ConversationSeed } from "../lib/chat-surface";
import type { SessionResultSurface } from "../lib/session-results";
import type { SessionArtifactDetailResponse, SessionEvent, SessionSummary } from "../types";
import { CodexConversationPane } from "./CodexConversationPane";
import { CodexSidebar } from "./CodexSidebar";
import type { GetRef } from "antd";
import type { Sender } from "@ant-design/x";

const useStyle = createStyles(({ css }) => {
  return {
    shell: css`
      width: 100%;
      min-height: 100vh;
      display: grid;
      grid-template-columns: 1fr;
      row-gap: var(--zebra-space-sm);
      background:
        radial-gradient(circle at top left, rgba(255, 255, 255, 0.05), transparent 26%),
        linear-gradient(180deg, #191919 0%, #141414 100%);
      color: rgba(255, 255, 255, 0.92);
      @media (min-width: 1020px) {
        grid-template-columns: minmax(var(--zebra-sidebar-width), auto) minmax(0, 1fr);
        column-gap: var(--zebra-space-sm);
        row-gap: 0;
      }
    `,
  };
});

interface CodexWorkspaceProps {
  activeLabel: string;
  apiBaseUrl: string;
  artifactContentPreview: string | null;
  artifactDetail: SessionArtifactDetailResponse | null;
  artifactLoading: boolean;
  conversations: ConversationSeed[];
  conversationSessionIds: Record<string, string>;
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
  sessionSummaries: Record<string, SessionSummary | null>;
  sessionSummary: SessionSummary | null;
  senderRef: React.RefObject<GetRef<typeof Sender> | null>;
}

export function CodexWorkspace(props: CodexWorkspaceProps) {
  const { styles } = useStyle();

  return (
    <XProvider locale={locale as any}>
      <div className={styles.shell}>
        <CodexSidebar
          conversations={props.conversations}
          conversationSessionIds={props.conversationSessionIds}
          currentConversation={props.currentConversation}
          onCreateConversation={props.onCreateConversation}
          onDeleteConversation={props.onDeleteConversation}
          onSelectConversation={props.onSelectConversation}
          sessionSummaries={props.sessionSummaries}
        />
        <CodexConversationPane
          activeLabel={props.activeLabel}
          apiBaseUrl={props.apiBaseUrl}
          artifactContentPreview={props.artifactContentPreview}
          artifactDetail={props.artifactDetail}
          artifactLoading={props.artifactLoading}
          currentConversation={props.currentConversation}
          currentSessionId={props.currentSessionId}
          events={props.events}
          isRequesting={props.isRequesting}
          listRef={props.listRef}
          messages={props.messages}
          onCancel={props.onCancel}
          onCloseArtifact={props.onCloseArtifact}
          onCopySessionId={props.onCopySessionId}
          onCopyWorkspacePath={props.onCopyWorkspacePath}
          onCreateConversation={props.onCreateConversation}
          onCancelSession={props.onCancelSession}
          onResumeSession={props.onResumeSession}
          onSuspendSession={props.onSuspendSession}
          onOpenArtifact={props.onOpenArtifact}
          onRefreshConversation={props.onRefreshConversation}
          controlsBusy={props.controlsBusy}
          onScrollToLatest={props.onScrollToLatest}
          onSubmit={props.onSubmit}
          resultSurface={props.resultSurface}
          sessionSummary={props.sessionSummary}
          senderRef={props.senderRef}
        />
      </div>
    </XProvider>
  );
}
