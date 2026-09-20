/** Host-neutral Agent UI contracts. Components may depend on these; Host adapters implement them. */

export type AgentCapabilityMode = "research" | "general" | "coding";
export type AgentTaskType = "answer" | "research" | "change" | "create" | "operate";
export type AgentActivityKind = "narration" | "tool" | "subagent";
export type AgentActivityStatus =
  | "running"
  | "ready"
  | "completed"
  | "failed"
  | "cancelled";

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
