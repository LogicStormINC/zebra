import { XProvider } from "@ant-design/x";
import { Drawer } from "antd";
import { createStyles } from "antd-style";
import React, { useState } from "react";
import locale from "../_utils/local";
import type { ChatMessage, ConversationSeed } from "../lib/chat-surface";
import type { RuntimeConnectionStatus } from "../lib/runtime-connection";
import type { TextAttachmentPayload } from "../lib/text-attachments";
import { compactWorkspaceLabel, type TaskLaunchConfig } from "../lib/task-launch-config";
import { useTaskLaunchConfig } from "../lib/use-task-launch-config";
import {
  projectWorkspaceNavigation,
  UNBOUND_PROJECT_ID,
  workspaceProjectId,
  type WorkspaceProject,
} from "../lib/workspace-projects";
import type { ApprovalSummary, McpCapabilitiesResponse, OperatorConfig, SessionEvent, SessionSummary } from "../types";
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
  activeApproval: ApprovalSummary | undefined;
  approvalBusy: boolean;
  approvalErrorText: string | null;
  clarificationBusy: boolean;
  conversations: ConversationSeed[];
  currentConversation: string;
  currentSessionId?: string;
  events: SessionEvent[];
  hiddenSessionCount: number;
  isWorkspaceIdle: boolean;
  isRequesting: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
  messages: ChatMessage[];
  mcpCapabilities: McpCapabilitiesResponse | undefined;
  mcpCapabilitiesBusy: boolean;
  mcpCapabilitiesError: string | null;
  operatorConfig: OperatorConfig;
  onCancel: () => void;
  onCopySessionId: () => void;
  onCopyWorkspacePath: () => void;
  onPatchConfig: (patch: Partial<OperatorConfig>) => void;
  onResetConfig: () => void;
  onRestoreHiddenSessions: () => void;
  onRetryRuntime: () => void;
  onRetryMcpCapabilities: () => void;
  onCreateConversation: () => void;
  onDeleteConversation: (key: string) => void;
  onCancelSession: () => void;
  onResumeSession: () => void;
  onSuspendSession: () => void;
  onApprove: (approval: ApprovalSummary) => Promise<unknown>;
  onRefreshConversation: () => void;
  onReject: (approval: ApprovalSummary) => Promise<unknown>;
  onRespondClarification: (clarificationId: string, content: string) => Promise<unknown>;
  onScrollToLatest: () => void;
  onSelectConversation: (key: string) => void;
  onSubmit: (value: string, launchConfig: TaskLaunchConfig, attachments: TextAttachmentPayload[]) => Promise<boolean>;
  controlsBusy: boolean;
  runtimeStatus: RuntimeConnectionStatus;
  sessionSummaries: Record<string, SessionSummary | null>;
  sessionIds: Record<string, string>;
  sessionSummary: SessionSummary | null;
  senderRef: React.RefObject<GetRef<typeof Sender> | null>;
}

export function CodexWorkspace(props: CodexWorkspaceProps) {
  const { styles } = useStyle();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const launch = useTaskLaunchConfig();
  const runtimeLabel = props.runtimeStatus === "connected"
    ? locale.runtimeConnected
    : props.runtimeStatus === "checking"
      ? locale.runtimeChecking
      : locale.runtimeDisconnected;
  const projects = projectWorkspaceNavigation(
    props.conversations,
    props.sessionSummaries,
    launch.config.workspace,
  );
  const [selectedProjectId, setSelectedProjectId] = useState(
    () => workspaceProjectId(launch.config.workspace),
  );
  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? projects[0];
  const selectedProjectLabel = selectedProject?.workspaceRoot
    ? compactWorkspaceLabel(selectedProject.workspaceRoot)
    : locale.unboundProject;
  const visibleKeys = new Set(selectedProject?.conversationKeys ?? []);
  const visibleConversations = props.conversations.filter((conversation) => visibleKeys.has(conversation.key));
  const patchLaunchConfig = (patch: Partial<TaskLaunchConfig>) => {
    launch.patchConfig(patch);
    if (patch.workspace?.trim()) setSelectedProjectId(workspaceProjectId(patch.workspace));
  };
  const selectProject = (project: WorkspaceProject) => {
    setSelectedProjectId(project.id);
    if (project.workspaceRoot) launch.patchConfig({ workspace: project.workspaceRoot });
    props.onCreateConversation();
  };

  return (
    <XProvider locale={locale as any}>
      <>
        <div className={styles.shell}>
          <CodexSidebar
            conversations={visibleConversations}
            currentConversation={props.currentConversation}
            hiddenSessionCount={props.hiddenSessionCount}
            isWorkspaceIdle={props.isWorkspaceIdle}
            onCreateConversation={props.onCreateConversation}
            onDeleteConversation={props.onDeleteConversation}
            onRestoreHiddenSessions={props.onRestoreHiddenSessions}
            onSelectProject={selectProject}
            onSelectConversation={props.onSelectConversation}
            projects={projects}
            runtimeLabel={runtimeLabel}
            selectedProjectId={selectedProject?.id ?? UNBOUND_PROJECT_ID}
            sessionIds={props.sessionIds}
            sessionSummaries={props.sessionSummaries}
          />
          <CodexConversationPane
            activeLabel={props.activeLabel}
            activeApproval={props.activeApproval}
            approvalBusy={props.approvalBusy}
            approvalErrorText={props.approvalErrorText}
            clarificationBusy={props.clarificationBusy}
            conversations={visibleConversations}
            controlsBusy={props.controlsBusy}
            currentConversation={props.currentConversation}
            currentSessionId={props.currentSessionId}
            events={props.events}
            isRequesting={props.isRequesting}
            isWorkspaceIdle={props.isWorkspaceIdle}
            idleProjectLabel={selectedProjectLabel}
            idleProjectPath={selectedProject?.workspaceRoot ?? null}
            listRef={props.listRef}
            launchConfig={launch.config}
            mcpCapabilities={props.mcpCapabilities}
            mcpCapabilitiesBusy={props.mcpCapabilitiesBusy}
            mcpCapabilitiesError={props.mcpCapabilitiesError}
            messages={props.messages}
            onCancel={props.onCancel}
            onCancelSession={props.onCancelSession}
            onCopySessionId={props.onCopySessionId}
            onCopyWorkspacePath={props.onCopyWorkspacePath}
            onCreateConversation={props.onCreateConversation}
            onOpenSettings={() => setSettingsOpen(true)}
            onPatchLaunchConfig={patchLaunchConfig}
            onApprove={props.onApprove}
            onRefreshConversation={props.onRefreshConversation}
            onReject={props.onReject}
            onRespondClarification={props.onRespondClarification}
            onResumeSession={props.onResumeSession}
            onScrollToLatest={props.onScrollToLatest}
            onSelectConversation={props.onSelectConversation}
            onSubmit={props.onSubmit}
            onSuspendSession={props.onSuspendSession}
            runtimeStatus={props.runtimeStatus}
            senderRef={props.senderRef}
            sessionSummaries={props.sessionSummaries}
            sessionSummary={props.sessionSummary}
          />
        </div>
        <Drawer onClose={() => setSettingsOpen(false)} open={settingsOpen} title={locale.runtimeSettings} width={460}>
          <OperatorConfigCard
            config={props.operatorConfig}
            mcpCapabilities={props.mcpCapabilities}
            mcpCapabilitiesBusy={props.mcpCapabilitiesBusy}
            mcpCapabilitiesError={props.mcpCapabilitiesError}
            onChange={props.onPatchConfig}
            onReset={props.onResetConfig}
            onRetryMcpCapabilities={props.onRetryMcpCapabilities}
            onRetry={props.onRetryRuntime}
            runtimeStatus={props.runtimeStatus}
          />
        </Drawer>
      </>
    </XProvider>
  );
}
