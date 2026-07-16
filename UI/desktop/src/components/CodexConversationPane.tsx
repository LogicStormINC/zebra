import {
  ArrowDownOutlined,
  CopyOutlined,
  EllipsisOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SettingOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Sender } from "@ant-design/x";
import { Button, Dropdown, GetRef } from "antd";
import React from "react";
import locale from "../_utils/local";
import { sessionStatusLabel, sessionWorkspaceLabel } from "../_utils/session-status";
import type { ChatMessage, ConversationSeed } from "../lib/chat-surface";
import { availableMcpPrompts, availableMcpResourceIds, availableMcpToolNames } from "../lib/mcp-capabilities";
import type { RuntimeConnectionStatus } from "../lib/runtime-connection";
import { attachmentPayloads, type PendingTextAttachment, type TextAttachmentPayload } from "../lib/text-attachments";
import { validateTaskLaunchConfig, type TaskLaunchConfig } from "../lib/task-launch-config";
import type { ApprovalSummary, McpCapabilitiesResponse, McpPromptsResponse, SessionEvent, SessionSummary } from "../types";
import { useConversationPaneStyle } from "./CodexConversationPane.styles";
import { ConversationComposer } from "./conversation/ConversationComposer";
import { ConversationThread } from "./conversation/ConversationThread";
import { WorkspaceIdle } from "./conversation/WorkspaceIdle";

interface CodexConversationPaneProps {
  activeLabel: string;
  activeApproval: ApprovalSummary | undefined;
  approvalBusy: boolean;
  approvalErrorText: string | null;
  clarificationBusy: boolean;
  currentConversation: string;
  currentSessionId?: string;
  conversations: ConversationSeed[];
  events: SessionEvent[];
  idleProjectLabel: string;
  idleProjectPath: string | null;
  isWorkspaceIdle: boolean;
  isRequesting: boolean;
  listRef: React.RefObject<HTMLDivElement | null>;
  messages: ChatMessage[];
  launchConfig: TaskLaunchConfig;
  mcpCapabilities: McpCapabilitiesResponse | undefined;
  mcpCapabilitiesBusy: boolean;
  mcpCapabilitiesError: string | null;
  mcpPrompts: McpPromptsResponse | undefined;
  mcpPromptsBusy: boolean;
  mcpPromptsError: string | null;
  onCancel: () => void;
  onCopySessionId: () => void;
  onCopyWorkspacePath: () => void;
  onCreateConversation: () => void;
  onOpenSettings: () => void;
  onCancelSession: () => void;
  onResumeSession: () => void;
  onSuspendSession: () => void;
  onPatchLaunchConfig: (patch: Partial<TaskLaunchConfig>) => void;
  onRetryMcpPrompts: () => void;
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
  sessionSummary: SessionSummary | null;
  senderRef: React.RefObject<GetRef<typeof Sender> | null>;
}

export function CodexConversationPane(props: CodexConversationPaneProps) {
  const { styles } = useConversationPaneStyle();
  const [composerValue, setComposerValue] = React.useState("");
  const [pendingAttachments, setPendingAttachments] = React.useState<PendingTextAttachment[]>([]);
  React.useEffect(() => {
    setPendingAttachments([]);
  }, [props.currentConversation]);

  const hasThread = !props.isWorkspaceIdle;
  const hasSessionThread = Boolean(props.currentSessionId) || props.messages.length > 0 || props.events.length > 0;
  const launchEditable = !props.currentSessionId;
  const durableWorkspace = props.sessionSummary?.workspace?.workspace_root ?? "";
  const durablePolicy = props.sessionSummary?.workspace?.policy_profile === "full_access" ? "full_access" : "workspace_write";
  const durableToolProfile = props.sessionSummary?.workspace?.tool_profile === "general" ? "general" : "coding";
  const durableNetworkProfile = props.sessionSummary?.workspace?.network_profile === "domain-allowlist"
    || props.sessionSummary?.workspace?.network_profile === "mcp-proxy-only"
    ? props.sessionSummary.workspace.network_profile
    : "none";
  const durableMcpResourceIds = props.sessionSummary?.attachments
    ?.filter((attachment) => attachment.source_type === "mcp_resource")
    .flatMap((attachment) => attachment.source_id ? [attachment.source_id] : []) ?? [];
  const effectiveLaunchConfig: TaskLaunchConfig = launchEditable
    ? props.launchConfig
    : {
        workspace: durableWorkspace,
        policyProfile: durablePolicy,
        toolProfile: durableToolProfile,
        networkProfile: durableNetworkProfile,
        networkAllowlist: props.sessionSummary?.workspace?.network_allowlist ?? [],
        mcpAllowlist: props.sessionSummary?.workspace?.mcp_allowlist ?? [],
        mcpResourceIds: durableMcpResourceIds,
        mcpPromptId: null,
        mcpPromptArguments: {},
        mcpPromptSchema: null,
      };
  const launchError = validateTaskLaunchConfig(
    effectiveLaunchConfig,
    launchEditable ? availableMcpToolNames(props.mcpCapabilities) : undefined,
    launchEditable ? availableMcpResourceIds(props.mcpCapabilities) : undefined,
    launchEditable && (props.mcpPrompts || props.mcpPromptsError)
      ? props.mcpPromptsError ? [] : availableMcpPrompts(props.mcpPrompts)
      : undefined,
  );
  const headerTitle = hasThread ? props.activeLabel : props.idleProjectLabel;
  const runtimeLabel = props.runtimeStatus === "connected"
    ? locale.runtimeConnected
    : props.runtimeStatus === "checking" ? locale.runtimeChecking : locale.runtimeDisconnected;
  const headerMeta = hasThread
    ? props.currentSessionId
      ? `${sessionStatusLabel(props.sessionSummary?.status)} · ${sessionWorkspaceLabel(props.sessionSummary)} · ${props.currentSessionId.slice(0, 8)}`
      : `${locale.statusDraft} · ${locale.notBound} · ${locale.notStarted}`
    : runtimeLabel;

  const submitComposer = async (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || launchError) return;
    const submitted = await props.onSubmit(trimmed, effectiveLaunchConfig, attachmentPayloads(pendingAttachments));
    if (submitted) {
      setComposerValue("");
      setPendingAttachments([]);
    }
  };
  const submitQuickAction = (prompt: string) => {
    void props.onSubmit(prompt, effectiveLaunchConfig, attachmentPayloads(pendingAttachments)).then((submitted) => {
      if (submitted) setPendingAttachments([]);
    });
  };
  const renderComposer = (variant: "idle" | "thread") => (
    <ConversationComposer
      attachments={pendingAttachments}
      canSubmit={composerValue.trim().length > 0 && !launchError}
      currentConversation={props.currentConversation}
      effectiveLaunchConfig={effectiveLaunchConfig}
      isRequesting={props.isRequesting}
      launchConfig={props.launchConfig}
      launchEditable={launchEditable}
      launchError={launchError}
      mcpCapabilities={props.mcpCapabilities}
      mcpCapabilitiesBusy={props.mcpCapabilitiesBusy}
      mcpCapabilitiesError={props.mcpCapabilitiesError}
      mcpPrompts={props.mcpPrompts}
      mcpPromptsBusy={props.mcpPromptsBusy}
      mcpPromptsError={props.mcpPromptsError}
      onAttachmentsChange={setPendingAttachments}
      onCancel={props.onCancel}
      onChange={setComposerValue}
      onPatchLaunchConfig={props.onPatchLaunchConfig}
      onRetryMcpPrompts={props.onRetryMcpPrompts}
      onSubmit={submitComposer}
      senderRef={props.senderRef}
      sessionSummary={props.sessionSummary}
      value={composerValue}
      variant={variant}
    />
  );
  const workspaceMenuItems = [
    { key: "copy-workspace", icon: <FolderOpenOutlined />, label: locale.copyWorkspacePath, onClick: props.onCopyWorkspacePath, disabled: !durableWorkspace },
    { key: "copy-session", icon: <CopyOutlined />, label: locale.copySessionId, onClick: props.onCopySessionId, disabled: !props.currentSessionId },
    { key: "refresh-session", icon: <ReloadOutlined />, label: locale.refreshConversation, onClick: props.onRefreshConversation, disabled: !props.currentSessionId },
  ];
  const sessionMenuItems = [
    { key: "new-conversation", icon: <PlusOutlined />, label: locale.newConversation, onClick: props.onCreateConversation },
    { key: "suspend-session", icon: <PauseCircleOutlined />, label: locale.suspendSession, onClick: props.onSuspendSession, disabled: !props.currentSessionId || props.controlsBusy },
    { key: "resume-session", icon: <PlayCircleOutlined />, label: locale.resumeSession, onClick: props.onResumeSession, disabled: !props.currentSessionId || props.controlsBusy },
    { key: "cancel-session", icon: <StopOutlined />, label: locale.cancelSession, onClick: props.onCancelSession, disabled: !props.currentSessionId || props.controlsBusy },
    { key: "scroll-latest", icon: <ArrowDownOutlined />, label: locale.scrollToLatest, onClick: props.onScrollToLatest, disabled: props.messages.length === 0 },
    { key: "copy-session", icon: <CopyOutlined />, label: locale.copySessionId, onClick: props.onCopySessionId, disabled: !props.currentSessionId },
  ];

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div className={styles.titleWrap}>
          <span className={styles.titleIcon}><FileTextOutlined /></span>
          <div className={styles.titleBlock}>
            <h1 title={hasThread ? undefined : props.idleProjectPath ?? locale.workspaceUnbound}>{headerTitle}</h1>
            <span className={styles.titleMeta}>{headerMeta}</span>
          </div>
        </div>
        <div className={styles.headerActions}>
          <Dropdown menu={{ items: workspaceMenuItems }} trigger={["click"]}>
            <Button className={styles.workspaceBadge} disabled={!durableWorkspace} icon={<FolderOpenOutlined />} type="default">
              {locale.workspaceBadge}
            </Button>
          </Dropdown>
          <Button aria-label={locale.runtimeSettings} className={styles.actionButton} icon={<SettingOutlined />} onClick={props.onOpenSettings} type="default" />
          <Button className={styles.actionButton} icon={<ReloadOutlined />} onClick={props.onRefreshConversation} type="default" />
          <Dropdown menu={{ items: sessionMenuItems }} trigger={["click"]}>
            <Button className={styles.actionButton} icon={<EllipsisOutlined />} type="default" />
          </Dropdown>
        </div>
      </header>
      <div className={styles.center}>
        {props.isWorkspaceIdle ? (
          <div className={styles.stream} ref={props.listRef}>
            <div className={styles.streamInner}>
              <WorkspaceIdle
                composer={renderComposer("idle")}
                conversations={props.conversations}
                currentConversation={props.currentConversation}
                launchError={launchError}
                onQuickAction={submitQuickAction}
                onSelectConversation={props.onSelectConversation}
                sessionSummaries={props.sessionSummaries}
              />
            </div>
          </div>
        ) : (
          <ConversationThread
            activeApproval={props.activeApproval}
            activeLabel={props.activeLabel}
            approvalBusy={props.approvalBusy}
            approvalErrorText={props.approvalErrorText}
            clarificationBusy={props.clarificationBusy}
            composer={renderComposer("thread")}
            events={props.events}
            isDraft={!hasSessionThread}
            listRef={props.listRef}
            messages={props.messages}
            onApprove={props.onApprove}
            onReject={props.onReject}
            onRespondClarification={props.onRespondClarification}
            sessionSummary={props.sessionSummary}
          />
        )}
      </div>
    </main>
  );
}
