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
export type AgentContentState = "processing" | "ready" | "failed";
export type AgentArtifactPurpose = "preview" | "download" | "poster" | "captions" | "data";
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
export type AgentTurnStatus =
  | "queued"
  | "running"
  | "waiting"
  | "completed"
  | "partial"
  | "blocked"
  | "failed"
  | "cancelled";

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

export interface AgentWorkSegment {
  id: string;
  label?: string;
  activities: readonly AgentActivity[];
}

export interface AgentMessage {
  id: string;
  role: AgentMessageRole;
  /** Legacy plain/Markdown content. New rich messages should also provide ordered parts. */
  content: string;
  parts?: readonly AgentContentPart[];
  status: AgentMessageStatus;
  timestampLabel?: string;
}

export interface AgentContentPartBase {
  id: string;
  state: AgentContentState;
}

export interface AgentTextPart extends AgentContentPartBase {
  type: "text";
  format: "markdown" | "plain";
  text: string;
}

export interface AgentArtifactPartBase extends AgentContentPartBase {
  artifactId: string;
  fileName?: string;
  mimeType: string;
  sizeBytes?: number;
}

export interface AgentImagePart extends AgentArtifactPartBase {
  type: "image";
  alt: string;
  height?: number;
  thumbnailArtifactId?: string;
  width?: number;
}

export interface AgentVideoPart extends AgentArtifactPartBase {
  type: "video";
  captionsArtifactId?: string;
  captionsLanguage?: string;
  description?: string;
  durationMs?: number;
  height?: number;
  posterArtifactId?: string;
  title: string;
  transcriptArtifactId?: string;
  width?: number;
}

export type AgentJsonValue =
  | boolean
  | number
  | string
  | null
  | readonly AgentJsonValue[]
  | { readonly [key: string]: AgentJsonValue };

export interface AgentChartPart extends AgentContentPartBase {
  type: "chart";
  specType: "vega-lite";
  specVersion: string;
  spec?: AgentJsonValue;
  specArtifactId?: string;
  dataArtifactId?: string;
  fallbackImageArtifactId?: string;
  fallbackTableArtifactId?: string;
  table?: AgentChartTable;
  title: string;
  description: string;
}

export interface AgentChartTable {
  columns: readonly string[];
  rows: readonly (readonly AgentJsonValue[])[];
}

export interface AgentFilePart extends AgentArtifactPartBase {
  type: "file";
  description?: string;
  name: string;
}

export interface AgentAppPart extends AgentContentPartBase {
  type: "app";
  resourceUri: `ui://${string}`;
  title: string;
  description?: string;
  fallbackArtifactId?: string;
  requestedCapabilities?: readonly string[];
}

export type AgentContentPart =
  | AgentTextPart
  | AgentImagePart
  | AgentVideoPart
  | AgentChartPart
  | AgentFilePart
  | AgentAppPart;

export interface AgentArtifactAccess {
  artifactId: string;
  expiresAtMs?: number;
  mimeType: string;
  url: string;
}

export interface AgentAppResource {
  allowedOrigin: string;
  capabilities: readonly string[];
  resourceUri: `ui://${string}`;
  url: string;
  version: "2025-11-21";
}

/** One durable user request and the public work/output that belongs to it. */
export interface AgentConversationTurn {
  id: string;
  status: AgentTurnStatus;
  userMessage?: AgentMessage;
  workSegments: readonly AgentWorkSegment[];
  assistantMessage?: AgentMessage;
  artifacts?: readonly AgentArtifact[];
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
  contextBreakdown?: readonly AgentComposerMetricPart[];
  contextLimit: number | null;
  contextPercent: number | null;
  contextTokens: number | null;
}

export interface AgentComposerMetricPart {
  id: string;
  label: string;
  tokens: number;
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
