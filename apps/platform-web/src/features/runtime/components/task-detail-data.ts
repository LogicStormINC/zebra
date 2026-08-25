import type {
  AgentDefinition,
  AgentRelease,
  Approval,
  Artifact,
  AuditEntry,
  Attempt,
  BackendManifest,
  ClientEffect,
  ClientRunBinding,
  ClientSession,
  FrontendProfile,
  Host,
  HostEffect,
  ModelCall,
  MountedCapabilitySnapshot,
  OrchestrationRun,
  PolicyRecord,
  SubagentLink,
  Task,
  TaskEvent,
  ToolCall
} from '@/lib/platform/types';

/** Task 详情页（PRD 18）的服务器取数结果：全部可序列化。 */
export type TaskDetailData = {
  task: Task;
  release?: AgentRelease;
  definition?: AgentDefinition;
  events: TaskEvent[];
  attempts: Attempt[];
  modelCalls: ModelCall[];
  toolCalls: ToolCall[];
  hostEffects: HostEffect[];
  artifacts: Artifact[];
  orchestration?: OrchestrationRun;
  subagents: SubagentLink[];
  approvals: Approval[];
  memoryPolicy?: PolicyRecord;
  host?: Host;
  manifest?: BackendManifest;
  frontendProfile?: FrontendProfile;
  clientRunBindings: ClientRunBinding[];
  clientSessions: ClientSession[];
  mountedSnapshots: MountedCapabilitySnapshot[];
  clientEffects: ClientEffect[];
  auditEntries: AuditEntry[];
};

/** Task 级预算上限（演示用静态值）。 */
export const TASK_BUDGET_TOKENS = 200_000;
export const TASK_BUDGET_USD = 5;
