/** Host-neutral Agent UI contracts. Components may depend on these; Host adapters implement them. */

export type AgentCapabilityMode = "research" | "general" | "coding";
export type AgentTaskType = "answer" | "research" | "change" | "create" | "operate";
export type AgentActivityKind = "narration" | "tool" | "subagent";
export type AgentActivityStatus =
  | "running"
  | "ready"
  | "completed"
  | "blocked"
  | "failed"
  | "cancelled";
export type AgentMessageRole = "user" | "assistant" | "system";
export type AgentMessageStatus = "sending" | "streaming" | "complete" | "failed";
export type AgentArtifactStatus = "ready" | "processing" | "failed";
export type AgentRunPhase =
  | "idle"
  | "submitting"
  | "accepted"
  | "queued"
  | "running"
  | "waiting_for_user"
  | "paused"
  | "reconciling"
  | "disconnected"
  | "terminal";
export type AgentRunOutcome = "completed" | "partial" | "blocked" | "failed" | "cancelled";
export type AgentRecoveryAction = "reconnect" | "resume" | "retry";

interface AgentRunStateBase {
  /** Opaque support identifier. Raw errors and stack traces do not belong in this contract. */
  diagnosticId?: string;
  /** Host-approved user-facing text only. */
  safeMessage?: string;
  availableActions: readonly AgentRecoveryAction[];
}

export type AgentRunState =
  | (AgentRunStateBase & {
      phase: Exclude<AgentRunPhase, "queued" | "terminal">;
      outcome?: never;
      queuePosition?: never;
    })
  | (AgentRunStateBase & {
      phase: "queued";
      outcome?: never;
      queuePosition?: number;
    })
  | (AgentRunStateBase & {
      phase: "terminal";
      outcome: AgentRunOutcome;
      queuePosition?: never;
    });

export interface AgentDeliveryAssessment {
  status: "complete" | "partial" | "blocked";
  taskType?: AgentTaskType;
  goal?: string;
  satisfied: readonly string[];
  unmet: readonly string[];
  requiredOutcomes?: readonly string[];
  evidenceRefs: readonly string[];
  artifactRefs: readonly string[];
}

export interface AgentActivity {
  activityId: string;
  kind: AgentActivityKind;
  status: AgentActivityStatus;
  title: string;
  description?: string;
  startedAtMs?: number;
  completedAtMs?: number;
  durationMs?: number;
}

export interface AgentMessage {
  id: string;
  role: AgentMessageRole;
  content: string;
  status: AgentMessageStatus;
  timestampLabel?: string;
}

export interface AgentArtifact {
  id: string;
  name: string;
  kind: string;
  status: AgentArtifactStatus;
  metadataLabel?: string;
}

export interface AgentMemorySetting {
  id: string;
  label: string;
  description: string;
  enabled: boolean;
  disabled?: boolean;
}

export interface AgentComposerMetrics {
  cacheHitRate: number | null;
  contextLimit: number | null;
  contextPercent: number | null;
  contextTokens: number | null;
}

export interface AgentComposerOption<T extends string = string> {
  label: string;
  value: T;
}

export interface AgentComposerAttachment {
  id: string;
  isImage: boolean;
  name: string;
}

export interface AgentTurnSubmission {
  message: string;
  capabilityMode: AgentCapabilityMode;
  modelProfile: string;
  reasoningEffort: string;
  attachments: readonly AgentComposerAttachment[];
}

export interface AgentUiHostAdapter {
  submit(input: AgentTurnSubmission): Promise<void>;
  pause(): Promise<void>;
  continue(): Promise<void>;
  removeAttachment(id: string): void;
  selectFiles(files: FileList | null): Promise<void> | void;
}
