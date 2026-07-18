import { Sender } from "@ant-design/x";
import { Flex, GetRef, Input, Tooltip } from "antd";
import React from "react";
import locale from "../../_utils/local";
import type { PendingAttachment } from "../../lib/text-attachments";
import type { TaskLaunchConfig } from "../../lib/task-launch-config";
import type { McpCapabilitiesResponse, McpPromptsResponse, SessionSummary } from "../../types";
import { ComposerAttachments } from "../ComposerAttachments";
import { useConversationPaneStyle } from "../CodexConversationPane.styles";
import { TaskLaunchSummary } from "../TaskLaunchSummary";
import { useTaskLaunchStyle } from "../TaskLaunchConfig.styles";
import { TaskLaunchControls } from "./TaskLaunchControls";

const NamedComposerInput = React.forwardRef<
  GetRef<typeof Input.TextArea>,
  React.ComponentProps<typeof Input.TextArea>
>((props, ref) => <Input.TextArea {...props} name="task-prompt" ref={ref} />);

interface ConversationComposerProps {
  attachments: PendingAttachment[];
  canSubmit: boolean;
  currentConversation: string;
  effectiveLaunchConfig: TaskLaunchConfig;
  isRequesting: boolean;
  launchConfig: TaskLaunchConfig;
  launchEditable: boolean;
  launchError: string | null;
  mcpCapabilities: McpCapabilitiesResponse | undefined;
  mcpCapabilitiesBusy: boolean;
  mcpCapabilitiesError: string | null;
  mcpPrompts: McpPromptsResponse | undefined;
  mcpPromptsBusy: boolean;
  mcpPromptsError: string | null;
  onAttachmentsChange: (attachments: PendingAttachment[]) => void;
  onCancel: () => void;
  onChange: (value: string) => void;
  onPatchLaunchConfig: (patch: Partial<TaskLaunchConfig>) => void;
  onRetryMcpPrompts: () => void;
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
  effectiveLaunchConfig,
  isRequesting,
  launchConfig,
  launchEditable,
  launchError,
  mcpCapabilities,
  mcpCapabilitiesBusy,
  mcpCapabilitiesError,
  mcpPrompts,
  mcpPromptsBusy,
  mcpPromptsError,
  onAttachmentsChange,
  onCancel,
  onChange,
  onPatchLaunchConfig,
  onRetryMcpPrompts,
  onSubmit,
  senderRef,
  sessionSummary,
  value,
  variant,
}: ConversationComposerProps) {
  const { styles } = useConversationPaneStyle();
  const { styles: launchStyles } = useTaskLaunchStyle();

  return (
    <div className={variant === "idle" ? styles.idleComposerCard : styles.composerCard}>
      {launchEditable ? (
        <TaskLaunchSummary
          className={launchStyles.summary}
          config={effectiveLaunchConfig}
          editable
          errorText={launchError}
          sessionSummary={sessionSummary}
        />
      ) : null}
      <ComposerAttachments attachments={attachments} disabled={isRequesting} onChange={onAttachmentsChange} />
      <div className={styles.sender}>
        <Sender
          autoSize={variant === "idle" ? { minRows: 1, maxRows: 6 } : { minRows: 2, maxRows: 3 }}
          components={{ input: NamedComposerInput }}
          footer={(actionNode) => (
            <Flex align="center" className={styles.composerFooter} justify="space-between">
              <TaskLaunchControls
                capabilities={mcpCapabilities}
                capabilitiesBusy={mcpCapabilitiesBusy}
                capabilitiesError={mcpCapabilitiesError}
                prompts={mcpPrompts}
                promptsBusy={mcpPromptsBusy}
                promptsError={mcpPromptsError}
                config={launchConfig}
                editable={launchEditable}
                onPatch={onPatchLaunchConfig}
                onRetryPrompts={onRetryMcpPrompts}
              />
              <Tooltip title={isRequesting ? "停止任务" : "发送任务"}>
                <span className={`${styles.sendSlot} ${canSubmit || isRequesting ? "" : styles.sendSlotDisabled}`}>
                  {React.isValidElement(actionNode)
                    ? React.cloneElement(actionNode as React.ReactElement<{ "aria-label"?: string }>, {
                        "aria-label": isRequesting ? "停止任务" : "发送任务",
                      })
                    : actionNode}
                </span>
              </Tooltip>
            </Flex>
          )}
          key={`${variant}-${currentConversation}`}
          loading={isRequesting}
          onCancel={onCancel}
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
