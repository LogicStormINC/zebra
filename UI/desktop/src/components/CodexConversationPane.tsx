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
  SettingOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Sender } from "@ant-design/x";
import { Button, Dropdown, Flex, GetRef, Input, Popover } from "antd";
import React from "react";
import locale from "../_utils/local";
import { sessionStatusLabel, sessionWorkspaceLabel } from "../_utils/session-status";
import type { ChatMessage, ConversationSeed } from "../lib/chat-surface";
import type { RuntimeConnectionStatus } from "../lib/runtime-connection";
import { availableMcpToolNames } from "../lib/mcp-capabilities";
import {
  attachmentPayloads,
  type PendingTextAttachment,
  type TextAttachmentPayload,
} from "../lib/text-attachments";
import { compactWorkspaceLabel, validateTaskLaunchConfig, type TaskLaunchConfig } from "../lib/task-launch-config";
import type { ApprovalSummary, McpCapabilitiesResponse, SessionEvent, SessionSummary } from "../types";
import { SessionThreadWorkspace } from "./SessionThreadWorkspace";
import { ComposerAttachments } from "./ComposerAttachments";
import { McpTaskSelector } from "./McpTaskSelector";
import { TaskLaunchSummary } from "./TaskLaunchSummary";
import { useTaskLaunchStyle } from "./TaskLaunchConfig.styles";
import { useConversationPaneStyle } from "./CodexConversationPane.styles";

const NamedComposerInput = React.forwardRef<
  GetRef<typeof Input.TextArea>,
  React.ComponentProps<typeof Input.TextArea>
>((props, ref) => <Input.TextArea {...props} name="task-prompt" ref={ref} />);

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
  onCancel: () => void;
  onCopySessionId: () => void;
  onCopyWorkspacePath: () => void;
  onCreateConversation: () => void;
  onOpenSettings: () => void;
  onCancelSession: () => void;
  onResumeSession: () => void;
  onSuspendSession: () => void;
  onPatchLaunchConfig: (patch: Partial<TaskLaunchConfig>) => void;
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

export function CodexConversationPane({
  activeLabel,
  activeApproval,
  approvalBusy,
  approvalErrorText,
  clarificationBusy,
  currentConversation,
  currentSessionId,
  conversations,
  events,
  idleProjectLabel,
  idleProjectPath,
  isWorkspaceIdle,
  isRequesting,
  listRef,
  messages,
  launchConfig,
  mcpCapabilities,
  mcpCapabilitiesBusy,
  mcpCapabilitiesError,
  onCancel,
  onCopySessionId,
  onCopyWorkspacePath,
  onCreateConversation,
  onOpenSettings,
  onCancelSession,
  onResumeSession,
  onSuspendSession,
  onPatchLaunchConfig,
  onApprove,
  onRefreshConversation,
  onReject,
  onRespondClarification,
  onScrollToLatest,
  onSelectConversation,
  onSubmit,
  controlsBusy,
  runtimeStatus,
  sessionSummaries,
  sessionSummary,
  senderRef,
}: CodexConversationPaneProps) {
  const { styles } = useConversationPaneStyle();
  const { styles: launchStyles } = useTaskLaunchStyle();
  const [composerValue, setComposerValue] = React.useState("");
  const [pendingAttachments, setPendingAttachments] = React.useState<PendingTextAttachment[]>([]);
  React.useEffect(() => {
    setPendingAttachments([]);
  }, [currentConversation]);
  const hasThread = !isWorkspaceIdle;
  const hasSessionThread = Boolean(currentSessionId) || messages.length > 0 || events.length > 0;
  const launchEditable = !currentSessionId;
  const durableWorkspace = sessionSummary?.workspace?.workspace_root ?? "";
  const durablePolicy = sessionSummary?.workspace?.policy_profile === "full_access" ? "full_access" : "workspace_write";
  const durableToolProfile = sessionSummary?.workspace?.tool_profile === "general" ? "general" : "coding";
  const durableNetworkProfile = sessionSummary?.workspace?.network_profile === "domain-allowlist" || sessionSummary?.workspace?.network_profile === "mcp-proxy-only" ? sessionSummary.workspace.network_profile : "none";
  const durableNetworkAllowlist = sessionSummary?.workspace?.network_allowlist ?? [];
  const durableMcpAllowlist = sessionSummary?.workspace?.mcp_allowlist ?? [];
  const availableMcpTools = availableMcpToolNames(mcpCapabilities);
  const effectiveLaunchConfig: TaskLaunchConfig = launchEditable
    ? launchConfig
    : { workspace: durableWorkspace, policyProfile: durablePolicy, toolProfile: durableToolProfile, networkProfile: durableNetworkProfile, networkAllowlist: durableNetworkAllowlist, mcpAllowlist: durableMcpAllowlist };
  const launchError = validateTaskLaunchConfig(effectiveLaunchConfig, launchEditable ? availableMcpTools : undefined);
  const canSubmit = composerValue.trim().length > 0 && !launchError;
  const headerTitle = hasThread ? activeLabel : idleProjectLabel;
  const runtimeLabel = runtimeStatus === "connected"
    ? locale.runtimeConnected
    : runtimeStatus === "checking"
      ? locale.runtimeChecking
      : locale.runtimeDisconnected;
  const headerMeta = hasThread
    ? currentSessionId
      ? `${sessionStatusLabel(sessionSummary?.status)} · ${sessionWorkspaceLabel(sessionSummary)} · ${currentSessionId.slice(0, 8)}`
      : `${locale.statusDraft} · ${locale.notBound} · ${locale.notStarted}`
    : runtimeLabel;
  const suggestedActions = [
    { label: locale.hintDocs, prompt: "阅读当前工作空间中的资料，并总结关键结论。" },
    { label: locale.hintExplain, prompt: "解释当前任务上下文、约束和可用信息。" },
    { label: locale.hintDebug, prompt: "分析当前问题，给出有证据的原因和处理方案。" },
    { label: locale.hintImplement, prompt: "根据当前目标，使用可用工具完成下一步任务。" },
    { label: locale.hintShip, prompt: "验证当前结果，并列出验证证据和未解决风险。" },
  ];
  const recentThreads = conversations.filter((item) => item.key !== currentConversation).slice(0, 5);
  const threadMeta = (item: ConversationSeed) => {
    const dayLabel = item.group === locale.pinned ? locale.todayGroup : item.group;
    const summary = sessionSummaries[item.key];
    return `${sessionStatusLabel(summary?.status)} · ${dayLabel} · ${sessionWorkspaceLabel(summary)}`;
  };
  const workspaceEditor = (
    <div className={launchStyles.editor}>
      <strong>新任务工作区</strong>
      <Input
        aria-label="新任务工作区"
        name="task-workspace"
        onChange={(event) => onPatchLaunchConfig({ workspace: event.target.value })}
        placeholder="绝对路径或 ."
        status={launchConfig.workspace.trim() ? undefined : "error"}
        value={launchConfig.workspace}
      />
      <span>路径由本地 API 解析；`.` 表示 API 服务当前目录。</span>
    </div>
  );
  const networkEditor = (
    <div className={launchStyles.editor}>
      <strong>允许访问的域名</strong>
      <Input
        aria-label="允许访问的域名"
        onChange={(event) => onPatchLaunchConfig({ networkAllowlist: event.target.value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean) })}
        placeholder="docs.example.com, api.example.com"
        value={launchConfig.networkAllowlist.join(", ")}
      />
      <span>仅填写裸域名，使用逗号分隔；不接受协议、路径或通配符。</span>
    </div>
  );
  const mcpEditor = (
    <McpTaskSelector
      capabilities={mcpCapabilities}
      busy={mcpCapabilitiesBusy}
      errorText={mcpCapabilitiesError}
      className={launchStyles.editor}
      selected={launchConfig.mcpAllowlist}
      onChange={(mcpAllowlist) => onPatchLaunchConfig({ mcpAllowlist })}
    />
  );
  const renderComposer = (variant: "idle" | "thread") => (
    <div className={variant === "idle" ? styles.idleComposerCard : styles.composerCard}>
      <TaskLaunchSummary
        className={launchStyles.summary}
        config={effectiveLaunchConfig}
        editable={launchEditable}
        errorText={launchError}
        sessionSummary={sessionSummary}
      />
      <ComposerAttachments
        attachments={pendingAttachments}
        disabled={isRequesting}
        onChange={setPendingAttachments}
      />
      <div className={styles.sender}>
        <Sender
          autoSize={variant === "idle" ? { minRows: 1, maxRows: 6 } : { minRows: 2, maxRows: 3 }}
          components={{ input: NamedComposerInput }}
          footer={(actionNode) => (
            <Flex align="center" className={styles.composerFooter} justify="space-between">
              <Flex align="center" className={styles.composerTools} gap={8}>
                <span className={styles.modeSegment}>
                  <span className={styles.modePill}>{locale.modeAsk}</span>
                  <span className={styles.modePillActive}>{locale.modeAct}</span>
                </span>
                {launchEditable ? (
                  <Popover content={workspaceEditor} placement="topLeft" trigger="click">
                    <button className={styles.toolbarButton} type="button">工作区: {compactWorkspaceLabel(launchConfig.workspace)}</button>
                  </Popover>
                ) : <span className={launchStyles.staticBadge}>工作区: {compactWorkspaceLabel(durableWorkspace)}</span>}
                {launchEditable ? (
                  <Dropdown menu={{ items: [
                    { key: "workspace_write", label: "权限: 工作区写入", onClick: () => onPatchLaunchConfig({ policyProfile: "workspace_write" }) },
                    { key: "full_access", label: "权限: 完整访问（全部受控工具）", onClick: () => onPatchLaunchConfig({ policyProfile: "full_access" }) },
                  ] }} trigger={["click"]}>
                    <button className={styles.toolbarButton} type="button">
                      {launchConfig.policyProfile === "full_access" ? "权限: 完整访问" : locale.accessWorkspaceWrite}
                    </button>
                  </Dropdown>
                ) : <span className={launchStyles.staticBadge}>权限: {durablePolicy === "full_access" ? "完整访问" : "工作区写入"}</span>}
                {launchEditable ? (
                  <Dropdown menu={{ items: [
                    { key: "general", label: "能力: 通用工具", onClick: () => onPatchLaunchConfig({ toolProfile: "general" }) },
                    { key: "coding", label: "能力: 编码工具", onClick: () => onPatchLaunchConfig({ toolProfile: "coding" }) },
                  ] }} trigger={["click"]}>
                    <button className={styles.toolbarButton} type="button">
                      {launchConfig.toolProfile === "coding" ? "能力: 编码工具" : "能力: 通用工具"}
                    </button>
                  </Dropdown>
                ) : <span className={launchStyles.staticBadge}>能力: {durableToolProfile === "coding" ? "编码工具" : "通用工具"}</span>}
                {launchEditable ? (
                  <Dropdown menu={{ items: [
                    { key: "none", label: "网络: 无外部网络", onClick: () => onPatchLaunchConfig({ networkProfile: "none", networkAllowlist: [], mcpAllowlist: [] }) },
                    { key: "domain-allowlist", label: "网络: 域名白名单", onClick: () => onPatchLaunchConfig({ networkProfile: "domain-allowlist", mcpAllowlist: [] }) },
                    { key: "mcp-proxy-only", label: "网络: 仅 MCP 代理", onClick: () => onPatchLaunchConfig({ networkProfile: "mcp-proxy-only", networkAllowlist: [] }) },
                  ] }} trigger={["click"]}>
                    <button className={styles.toolbarButton} type="button">网络: {launchConfig.networkProfile === "none" ? "无外部网络" : launchConfig.networkProfile}</button>
                  </Dropdown>
                ) : <span className={launchStyles.staticBadge}>网络: {durableNetworkProfile}</span>}
                {launchEditable && launchConfig.networkProfile === "domain-allowlist" ? (
                  <Popover content={networkEditor} placement="topLeft" trigger="click">
                    <button className={styles.toolbarButton} type="button">域名: {launchConfig.networkAllowlist.length || "未配置"}</button>
                  </Popover>
                ) : null}
                {launchEditable && launchConfig.networkProfile === "mcp-proxy-only" ? (
                  <Popover content={mcpEditor} placement="topLeft" trigger="click">
                    <button className={styles.toolbarButton} type="button">MCP: {launchConfig.mcpAllowlist.length || "未选择"}</button>
                  </Popover>
                ) : null}
                <span className={launchStyles.staticBadge}>模型: API 运行时配置</span>
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
          onSubmit={async (value) => {
            const trimmed = value.trim();
            if (!trimmed || launchError) {
              return;
            }
            const submitted = await onSubmit(
              trimmed,
              effectiveLaunchConfig,
              attachmentPayloads(pendingAttachments),
            );
            if (submitted) {
              setComposerValue("");
              setPendingAttachments([]);
            }
          }}
          placeholder={variant === "thread" ? locale.threadComposerHint : locale.placeholder}
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
  ];

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div className={styles.titleWrap}>
          <span className={styles.titleIcon}>
            <FileTextOutlined />
          </span>
          <div className={styles.titleBlock}>
            <h1 title={hasThread ? undefined : idleProjectPath ?? locale.workspaceUnbound}>{headerTitle}</h1>
            <span className={styles.titleMeta}>{headerMeta}</span>
          </div>
        </div>
        <div className={styles.headerActions}>
          <Dropdown menu={{ items: workspaceMenuItems }} trigger={["click"]}>
            <Button
              className={styles.workspaceBadge}
              disabled={!sessionSummary?.workspace?.workspace_root}
              icon={<FolderOpenOutlined />}
              type="default"
            >
              {locale.workspaceBadge}
            </Button>
          </Dropdown>
          <Button
            aria-label={locale.runtimeSettings}
            className={styles.actionButton}
            icon={<SettingOutlined />}
            onClick={onOpenSettings}
            type="default"
          />
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
            {isWorkspaceIdle ? (
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
                        disabled={Boolean(launchError)}
                        onClick={() => {
                          void onSubmit(
                            action.prompt,
                            effectiveLaunchConfig,
                            attachmentPayloads(pendingAttachments),
                          ).then((submitted) => {
                            if (submitted) setPendingAttachments([]);
                          });
                        }}
                        type="button"
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                </section>
                <section className={styles.idleSection}>
                  <div className={styles.idleSectionTitle}>{locale.continueTasks}</div>
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
                        <span>{threadMeta(item)}</span>
                      </button>
                    ))}
                    {recentThreads.length === 0 ? (
                      <div className={styles.recentEmpty}>{locale.noRecentSessions}</div>
                    ) : null}
                  </div>
                </section>
              </div>
            ) : (
              <SessionThreadWorkspace
                activeLabel={activeLabel}
                activeApproval={activeApproval}
                approvalBusy={approvalBusy}
                approvalErrorText={approvalErrorText}
                clarificationBusy={clarificationBusy}
                events={events}
                isDraft={!hasSessionThread}
                messages={messages}
                onApprove={onApprove}
                onReject={onReject}
                onRespondClarification={onRespondClarification}
                sessionSummary={sessionSummary}
              />
            )}
          </div>
        </div>

        {hasThread && sessionSummary?.status !== "waiting_input" ? (
          <div className={styles.composerDock}>{renderComposer("thread")}</div>
        ) : null}
      </div>
    </main>
  );
}
