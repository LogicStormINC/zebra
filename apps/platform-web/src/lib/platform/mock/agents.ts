import type {
  AgentDefinition,
  AgentRelease,
  CapabilityProfile,
  PolicyRecord
} from '@/lib/platform/types';

/** Agent 资产 mock 数据：Trench 试点 Agent、通用执行器、Jazz 草稿。 */

export const mockAgentDefinitions: AgentDefinition[] = [
  {
    id: 'def_trench_code_reviewer',
    name: 'trench-code-reviewer',
    description: '交易系统变更审查助手：读取风险报告与持仓，产出审查意见与工单',
    latestDraftRevision: 6,
    latestVersion: 3,
    publishedReleaseId: 'rel_tr_cr_3',
    capabilityCeiling: ['position:read', 'risk:read', 'ticket:write'],
    modelPolicyId: 'pol_model_deepseek_roles',
    toolProfileId: 'cap_trench_backend',
    runtimeProfileId: 'pol_runtime_sandbox_std',
    memoryPolicyId: 'pol_memory_reviewer',
    status: 'published',
    updatedAt: '2026-08-25T15:00:00+08:00'
  },
  {
    id: 'def_trench_research',
    name: 'trench-market-research',
    description: '市场异动研究：编排子任务汇总多源证据并生成日报',
    latestDraftRevision: 4,
    latestVersion: 2,
    publishedReleaseId: 'rel_tr_research_2',
    capabilityCeiling: ['risk:read', 'web:search'],
    modelPolicyId: 'pol_model_deepseek_roles',
    toolProfileId: 'cap_trench_backend',
    runtimeProfileId: 'pol_runtime_sandbox_std',
    status: 'published',
    updatedAt: '2026-08-24T18:00:00+08:00'
  },
  {
    id: 'def_general_executor',
    name: 'general-executor',
    description: '通用工程执行器：沙箱内代码修改与验证',
    latestDraftRevision: 5,
    latestVersion: 2,
    publishedReleaseId: 'rel_gen_exec_2',
    capabilityCeiling: ['sandbox:exec', 'git:read', 'git:write'],
    modelPolicyId: 'pol_model_deepseek_roles',
    toolProfileId: 'cap_platform_tools',
    runtimeProfileId: 'pol_runtime_sandbox_std',
    status: 'published',
    updatedAt: '2026-08-23T09:30:00+08:00'
  },
  {
    id: 'def_jazz_content_copilot',
    name: 'jazz-content-copilot',
    description: 'Jazz 内容审核助手（接入中，草稿）',
    latestDraftRevision: 1,
    latestVersion: 0,
    capabilityCeiling: ['content:read'],
    modelPolicyId: 'pol_model_deepseek_roles',
    toolProfileId: 'cap_jazz_backend',
    runtimeProfileId: 'pol_runtime_sandbox_std',
    status: 'draft',
    updatedAt: '2026-08-25T11:30:00+08:00'
  }
];

export const mockAgentReleases: AgentRelease[] = [
  {
    id: 'rel_tr_cr_3',
    definitionId: 'def_trench_code_reviewer',
    definitionName: 'trench-code-reviewer',
    version: 3,
    channel: 'stable',
    boundHosts: 1,
    digest: 'aa10ff33cc8841dd9922cc8841dd9922cc8841dd',
    status: 'published',
    releasedBy: 'lukeding',
    releasedAt: '2026-08-24T10:00:00+08:00'
  },
  {
    id: 'rel_tr_cr_4',
    definitionId: 'def_trench_code_reviewer',
    definitionName: 'trench-code-reviewer',
    version: 4,
    channel: 'canary',
    boundHosts: 1,
    digest: 'bb21aa44dd9950ee0033dd9950ee0033dd9950ee',
    status: 'published',
    releasedBy: 'lukeding',
    releasedAt: '2026-08-25T16:00:00+08:00'
  },
  {
    id: 'rel_tr_research_2',
    definitionId: 'def_trench_research',
    definitionName: 'trench-market-research',
    version: 2,
    channel: 'stable',
    boundHosts: 1,
    digest: 'cc32bb55ee0061ff1144ee0061ff1144ee0061ff',
    status: 'published',
    releasedBy: 'platform-team',
    releasedAt: '2026-08-24T18:00:00+08:00'
  },
  {
    id: 'rel_gen_exec_2',
    definitionId: 'def_general_executor',
    definitionName: 'general-executor',
    version: 2,
    channel: 'stable',
    boundHosts: 2,
    digest: 'dd43cc66ff1172aa2255ff1172aa2255ff1172',
    status: 'published',
    releasedBy: 'lukeding',
    releasedAt: '2026-08-23T09:30:00+08:00'
  },
  {
    id: 'rel_gen_exec_1',
    definitionId: 'def_general_executor',
    definitionName: 'general-executor',
    version: 1,
    channel: 'stable',
    boundHosts: 0,
    digest: 'ee54dd77002283bb3366002283bb3366002283bb',
    status: 'deprecated',
    releasedBy: 'lukeding',
    releasedAt: '2026-08-20T09:00:00+08:00'
  }
];

export const mockCapabilityProfiles: CapabilityProfile[] = [
  {
    id: 'cap_trench_backend',
    name: 'trench-backend-capabilities',
    backendTools: [
      'trench.get_position',
      'trench.get_risk_report',
      'trench.create_ticket',
      'trench.update_ticket_status'
    ],
    clientActions: ['ui.highlight_ticket', 'ui.navigate_ticket'],
    readables: ['page.route', 'risk.report_id'],
    revision: 3,
    digest: 'aabb0011cc2244dd8899cc2244dd8899cc2244dd',
    status: 'published',
    updatedAt: '2026-08-24T10:00:00+08:00'
  },
  {
    id: 'cap_platform_tools',
    name: 'platform-standard-tools',
    backendTools: ['sandbox.exec', 'fs.read', 'fs.write', 'git.diff'],
    clientActions: [],
    readables: [],
    revision: 5,
    digest: 'bbcc1122dd3344ee9900dd3344ee9900dd3344ee',
    status: 'published',
    updatedAt: '2026-08-20T09:00:00+08:00'
  },
  {
    id: 'cap_jazz_backend',
    name: 'jazz-backend-capabilities',
    backendTools: ['jazz.list_drafts', 'jazz.get_content_policy'],
    clientActions: [],
    readables: ['page.route'],
    revision: 1,
    digest: 'ccdd2233ee4455ff0011ee4455ff0011ee4455ff',
    status: 'draft',
    updatedAt: '2026-08-25T11:00:00+08:00'
  }
];

export const mockPolicies: PolicyRecord[] = [
  {
    id: 'pol_model_deepseek_roles',
    name: 'deepseek-role-router',
    kind: 'model',
    level: 'platform',
    scope: 'platform/global',
    revision: 4,
    digest: '1100aabbccdd4455eeffccdd4455eeffccdd4455',
    status: 'published',
    updatedBy: 'lukeding',
    updatedAt: '2026-08-22T10:00:00+08:00'
  },
  {
    id: 'pol_tool_trench',
    name: 'trench-tool-policy',
    kind: 'tool',
    level: 'host',
    scope: 'host/trench',
    revision: 2,
    digest: '2211bbccddee5566ff00ddee5566ff00ddee5566',
    status: 'published',
    updatedBy: 'platform-team',
    updatedAt: '2026-08-21T10:00:00+08:00'
  },
  {
    id: 'pol_runtime_sandbox_std',
    name: 'sandbox-standard-runtime',
    kind: 'runtime',
    level: 'platform',
    scope: 'platform/global',
    revision: 7,
    digest: '3322ccddeeff66770011eeff66770011eeff6677',
    status: 'published',
    updatedBy: 'lukeding',
    updatedAt: '2026-08-18T14:00:00+08:00'
  },
  {
    id: 'pol_approval_high_risk',
    name: 'high-risk-approval-required',
    kind: 'approval',
    level: 'platform',
    scope: 'platform/global',
    revision: 3,
    digest: '4433ddeeff0077881122ff0077881122ff0077',
    status: 'published',
    updatedBy: 'security-team',
    updatedAt: '2026-08-15T09:00:00+08:00'
  },
  {
    id: 'pol_memory_reviewer',
    name: 'reviewer-memory-policy',
    kind: 'memory',
    level: 'agent-release',
    scope: 'agent-release/rel_tr_cr_3',
    revision: 1,
    digest: '5544eeff00118999223300118999223300118999',
    status: 'published',
    updatedBy: 'lukeding',
    updatedAt: '2026-08-24T10:00:00+08:00'
  },
  {
    id: 'pol_client_action_trench',
    name: 'trench-client-action-policy',
    kind: 'client-action',
    level: 'frontend-profile',
    scope: 'frontend-profile/fp_trench_web',
    revision: 2,
    digest: '6655ff0011229a00334411229a00334411229a00',
    status: 'published',
    updatedBy: 'platform-team',
    updatedAt: '2026-08-23T16:00:00+08:00'
  },
  {
    id: 'pol_capability_trench_prod',
    name: 'trench-production-ceiling',
    kind: 'capability',
    level: 'namespace',
    scope: 'namespace/trench/prod',
    revision: 3,
    digest: '776600112233ab1144552233ab1144552233ab1',
    status: 'published',
    updatedBy: 'platform-team',
    updatedAt: '2026-08-19T11:00:00+08:00'
  },
  {
    id: 'pol_network_egress_default',
    name: 'default-egress-restriction',
    kind: 'network',
    level: 'platform',
    scope: 'platform/global',
    revision: 5,
    digest: '887711223344bc2255663344bc2255663344bc2',
    status: 'published',
    updatedBy: 'security-team',
    updatedAt: '2026-08-12T13:00:00+08:00'
  }
];
