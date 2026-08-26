/**
 * 平台数据访问层（PRD 27.8 / 28.4）。
 *
 * 页面统一从这里取数，禁止散落手写 fetch。
 * 当前实现读取本地 mock（无后端阶段的开发基线）；
 * 接入 Management API 后，将本文件替换为 OpenAPI 生成的
 * platform-api-client 调用，页面组件保持不变。
 */
import { mockAgentDefinitions, mockAgentReleases, mockCapabilityProfiles, mockPolicies } from './mock/agents';
import { mockClientEffects, mockClientRunBindings, mockClientSessions, mockFrontendProfiles, mockMountedSnapshots } from './mock/clients';
import { mockAuditEntries, mockQuotas, mockReconciliation, mockSecurityFindings, mockUsage } from './mock/governance';
import { mockBindings, mockConnectors, mockHosts, mockManifests, mockTrusts } from './mock/integration';
import {
  mockApprovals,
  mockArtifacts,
  mockAttempts,
  mockHostEffects,
  mockModelCalls,
  mockOrchestrationRuns,
  mockSubagentLinks,
  mockTaskEvents,
  mockToolCalls,
  mockWorkers
} from './mock/runtime-detail';
import { mockTasks } from './mock/tasks';
import { mockConformanceRuns, mockDryRuns, mockEvaluations, mockReleaseGates, mockRollouts } from './mock/quality';
import {
  mockCredentialProviders,
  mockEnvironments,
  mockFeatureFlags,
  mockHealthChecks,
  mockNotificationRules,
  mockOperators
} from './mock/system';
import type {
  AgentDefinition,
  AgentRelease,
  Approval,
  Artifact,
  BackendManifest,
  CapabilityProfile,
  ClientEffect,
  ClientRunBinding,
  ClientSession,
  ConformanceRun,
  Connector,
  DryRun,
  EvaluationRun,
  FrontendProfile,
  Host,
  HostEffect,
  InboundTrust,
  ModelCall,
  NamespaceBinding,
  OrchestrationRun,
  PolicyRecord,
  Quota,
  ReleaseGate,
  Rollout,
  SubagentLink,
  Task,
  TaskEvent,
  ToolCall,
  UsageRecord,
  WorkerNode
} from '@/lib/platform/types';

export const repository = {
  hosts: (): Host[] => mockHosts,
  host: (id: string) => mockHosts.find((host) => host.id === id || host.appId === id),
  trusts: (): InboundTrust[] => mockTrusts,
  connectors: (): Connector[] => mockConnectors,
  connector: (id: string) => mockConnectors.find((connector) => connector.id === id),
  manifests: (): BackendManifest[] => mockManifests,
  manifest: (id: string) => mockManifests.find((manifest) => manifest.id === id),
  bindings: (): NamespaceBinding[] => mockBindings,

  agentDefinitions: (): AgentDefinition[] => mockAgentDefinitions,
  agentDefinition: (id: string) => mockAgentDefinitions.find((def) => def.id === id),
  agentReleases: (): AgentRelease[] => mockAgentReleases,
  capabilityProfiles: (): CapabilityProfile[] => mockCapabilityProfiles,
  policies: (): PolicyRecord[] => mockPolicies,

  tasks: (): Task[] => mockTasks,
  task: (id: string) => mockTasks.find((task) => task.id === id),
  taskEvents: (taskId: string): TaskEvent[] => mockTaskEvents[taskId] ?? [],
  attempts: (taskId: string) => mockAttempts[taskId] ?? [],
  modelCalls: (taskId: string): ModelCall[] => mockModelCalls[taskId] ?? [],
  toolCalls: (taskId: string): ToolCall[] => mockToolCalls[taskId] ?? [],
  hostEffects: (): HostEffect[] => mockHostEffects,
  hostEffectsForTask: (taskId: string) =>
    mockHostEffects.filter((effect) => effect.taskId === taskId),
  artifacts: (taskId?: string): Artifact[] =>
    taskId ? mockArtifacts.filter((artifact) => artifact.taskId === taskId) : mockArtifacts,
  orchestrations: (): OrchestrationRun[] => mockOrchestrationRuns,
  orchestration: (runRef: string) => mockOrchestrationRuns.find((run) => run.runRef === runRef),
  subagentLinks: (): SubagentLink[] => mockSubagentLinks,
  approvals: (): Approval[] => mockApprovals,
  workers: (): WorkerNode[] => mockWorkers,

  frontendProfiles: (): FrontendProfile[] => mockFrontendProfiles,
  frontendProfile: (id: string) => mockFrontendProfiles.find((profile) => profile.id === id),
  clientSessions: (): ClientSession[] => mockClientSessions,
  clientRunBindings: (): ClientRunBinding[] => mockClientRunBindings,
  clientEffects: (): ClientEffect[] => mockClientEffects,
  mountedSnapshots: () => mockMountedSnapshots,

  conformanceRuns: (): ConformanceRun[] => mockConformanceRuns,
  conformanceRun: (id: string) => mockConformanceRuns.find((run) => run.id === id),
  dryRuns: (): DryRun[] => mockDryRuns,
  rollouts: (): Rollout[] => mockRollouts,
  evaluations: (): EvaluationRun[] => mockEvaluations,
  releaseGates: (): ReleaseGate[] => mockReleaseGates,

  quotas: (): Quota[] => mockQuotas,
  usage: (): UsageRecord[] => mockUsage,
  auditEntries: () => mockAuditEntries,
  securityFindings: () => mockSecurityFindings,
  reconciliation: () => mockReconciliation,

  environments: () => mockEnvironments,
  operators: () => mockOperators,
  featureFlags: () => mockFeatureFlags,
  credentialProviders: () => mockCredentialProviders,
  notificationRules: () => mockNotificationRules,
  healthChecks: () => mockHealthChecks
};

export type PlatformRepository = typeof repository;
