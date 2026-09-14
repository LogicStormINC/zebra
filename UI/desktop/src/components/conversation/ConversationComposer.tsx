import { Sender } from "@ant-design/x";
import { ArrowUpOutlined, CaretRightOutlined, PauseOutlined } from "@ant-design/icons";
import { Button, Flex, GetRef, Input, Tooltip } from "antd";
import React from "react";
import locale from "../../_utils/local";
import type { PendingAttachment } from "../../lib/text-attachments";
import type { TaskLaunchConfig } from "../../lib/task-launch-config";
import type { McpCapabilitiesResponse, McpPromptsResponse, SessionEvent, SessionSummary } from "../../types";
import { ComposerAttachments } from "../ComposerAttachments";
import { useConversationPaneStyle } from "../CodexConversationPane.styles";
import { TaskLaunchSummary } from "../TaskLaunchSummary";
import { useTaskLaunchStyle } from "../TaskLaunchConfig.styles";
import { ContextUsageIndicator } from "./ContextUsageIndicator";
import { TaskLaunchControls } from "./TaskLaunchControls";

const NamedComposerInput = React.forwardRef<
  GetRef<typeof Input.TextArea>,
  React.ComponentProps<typeof Input.TextArea>
>((props, ref) => <Input.TextArea {...props} name="task-prompt" ref={ref} />);

interface ConversationComposerProps {
  attachments: PendingAttachment[];
  canSubmit: boolean;
  currentConversation: string;
  controlsBusy: boolean;
  effectiveLaunchConfig: TaskLaunchConfig;
  events: SessionEvent[];
  isRequesting: boolean;
  launchEditable: boolean;
  launchError: string | null;
  mcpCapabilities: McpCapabilitiesResponse | undefined;
  mcpCapabilitiesBusy: boolean;
  mcpCapabilitiesError: string | null;
  mcpPrompts: McpPromptsResponse | undefined;
  mcpPromptsBusy: boolean;
  mcpPromptsError: string | null;
  onAttachmentsChange: (attachments: PendingAttachment[]) => void;
  onChange: (value: string) => void;
  onPause: () => void;
  onPatchLaunchConfig: (patch: Partial<TaskLaunchConfig>) => void;
  onRetryMcpPrompts: () => void;
  onResume: () => void;
  onSubmit: (value: string) => Promise<void>;
  senderRef: React.RefObject<GetRef<typeof Sender> | null>;
  sessionSummary: SessionSummary | null;
  value: string;
  variant: "idle" | "thread";
}

export function ConversationComposer({
  attachments,
  canSubmit,
  currentConversation,
  controlsBusy,
  effectiveLaunchConfig,
  events,
  isRequesting,
  launchEditable,
  launchError,
  mcpCapabilities,
  mcpCapabilitiesBusy,
  mcpCapabilitiesError,
  mcpPrompts,
  mcpPromptsBusy,
  mcpPromptsError,
  onAttachmentsChange,
  onChange,
  onPause,
  onPatchLaunchConfig,
  onRetryMcpPrompts,
  onResume,
  onSubmit,
  senderRef,
  sessionSummary,
  value,
  variant,
}: ConversationComposerProps) {
  const { styles } = useConversationPaneStyle();
  const { styles: launchStyles } = useTaskLaunchStyle();
  const hasInput = value.trim().length > 0;
  const action = hasInput ? "send" : isRequesting ? "pause" : sessionSummary?.status === "suspended" ? "resume" : "send";
  const actionLabel = action === "pause" ? "暂停任务" : action === "resume" ? "继续任务" : "发送任务";
  const actionIcon = action === "pause" ? <PauseOutlined /> : action === "resume" ? <CaretRightOutlined /> : <ArrowUpOutlined />;
  const actionDisabled = controlsBusy || (action === "send" && !canSubmit);

  return (
    <div className={styles.composerCard}>
      {launchEditable && variant !== "idle" ? (
        <TaskLaunchSummary
          className={launchStyles.summary}
          config={effectiveLaunchConfig}
          editable
          errorText={launchError}
          sessionSummary={sessionSummary}
        />
      ) : null}
      <div className={styles.sender}>
        <Sender
          autoSize={{ minRows: 1, maxRows: 6 }}
          components={{ input: NamedComposerInput }}
          footer={() => (
            <Flex align="center" className={styles.composerFooter} justify="space-between">
              <Flex align="center" className={styles.composerActions} gap={8}>
                <ComposerAttachments attachments={attachments} disabled={controlsBusy} onChange={onAttachmentsChange} />
                <TaskLaunchControls
                  capabilities={mcpCapabilities}
                  capabilitiesBusy={mcpCapabilitiesBusy}
                  capabilitiesError={mcpCapabilitiesError}
                  prompts={mcpPrompts}
                  promptsBusy={mcpPromptsBusy}
                  promptsError={mcpPromptsError}
                  config={effectiveLaunchConfig}
                  editable={launchEditable}
                  onPatch={onPatchLaunchConfig}
                  onRetryPrompts={onRetryMcpPrompts}
                />
              </Flex>
              <Flex align="center" className={styles.composerRuntime} gap={6}>
                <ContextUsageIndicator events={events} />
                <Tooltip title={actionLabel}>
                  <span className={`${styles.sendSlot} ${actionDisabled ? styles.sendSlotDisabled : ""}`}>
                    <Button
                      aria-label={actionLabel}
                      disabled={actionDisabled}
                      icon={actionIcon}
                      onClick={() => action === "pause" ? onPause() : action === "resume" ? onResume() : void onSubmit(value)}
                      shape="circle"
                      type="primary"
                    />
                  </span>
                </Tooltip>
              </Flex>
            </Flex>
          )}
          key={`${variant}-${currentConversation}`}
          loading={false}
          onChange={onChange}
          onSubmit={onSubmit}
          placeholder={variant === "thread" ? locale.threadComposerHint : locale.placeholder}
          ref={senderRef}
          suffix={false}
          value={value}
        />
      </div>
    </div>
  );
}
