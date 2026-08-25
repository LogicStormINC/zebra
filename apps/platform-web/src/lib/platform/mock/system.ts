import type {
  CredentialProvider,
  EnvironmentRecord,
  FeatureFlag,
  NotificationRule,
  OperatorRecord,
  PlatformHealthCheck
} from '@/lib/platform/types';

/** 系统设置 mock 数据。 */

export const mockEnvironments: EnvironmentRecord[] = [
  {
    id: 'development',
    name: 'Development',
    apiEndpoint: 'https://api.dev.zebra.local',
    region: 'cn-east-1',
    hosts: 2,
    tasks24h: 58,
    status: 'healthy'
  },
  {
    id: 'staging',
    name: 'Staging',
    apiEndpoint: 'https://api.staging.zebra.local',
    region: 'cn-east-1',
    hosts: 1,
    tasks24h: 22,
    status: 'healthy'
  },
  {
    id: 'production',
    name: 'Production',
    apiEndpoint: 'https://api.zebra.example',
    region: 'cn-east-1 / cn-north-2',
    hosts: 1,
    tasks24h: 214,
    status: 'degraded'
  }
];

export const mockOperators: OperatorRecord[] = [
  {
    id: 'op_001',
    name: 'Luke Ding',
    email: 'lukeding@zebra.local',
    roles: ['Platform Owner', 'Platform Admin'],
    status: 'active',
    lastActiveAt: '2026-08-26T09:40:00+08:00'
  },
  {
    id: 'op_002',
    name: 'Runtime Ops',
    email: 'runtime-ops@zebra.local',
    roles: ['Runtime Operator'],
    status: 'active',
    lastActiveAt: '2026-08-26T09:10:00+08:00'
  },
  {
    id: 'op_003',
    name: 'Security Audit',
    email: 'security-audit@zebra.local',
    roles: ['Security Auditor'],
    status: 'active',
    lastActiveAt: '2026-08-26T08:10:00+08:00'
  },
  {
    id: 'op_004',
    name: 'Jazz Integrator',
    email: 'jazz-integrator@jazz.local',
    roles: ['Integration Engineer'],
    status: 'invited',
    lastActiveAt: '2026-08-25T11:30:00+08:00'
  }
];

export const mockFeatureFlags: FeatureFlag[] = [
  {
    key: 'client_effect_v2_fence',
    name: 'Client Effect V2 Fence',
    description: '启用 V2 多 Tab Fence（CAS Controller 抢占）',
    enabled: true,
    scope: 'platform',
    updatedAt: '2026-08-24T10:00:00+08:00'
  },
  {
    key: 'orchestration_dag_v2',
    name: 'Orchestration DAG V2',
    description: 'DAG Scheduler v2（含预算预留 Receipt）',
    enabled: true,
    scope: 'platform',
    updatedAt: '2026-08-22T14:00:00+08:00'
  },
  {
    key: 'frontend_hook_marketplace',
    name: 'Hook Marketplace',
    description: '业务侧 Hook 模板市场（P2 预留）',
    enabled: false,
    scope: 'platform',
    updatedAt: '2026-08-20T09:00:00+08:00'
  },
  {
    key: 'jazz_onboarding_ui',
    name: 'Jazz Onboarding',
    description: 'Jazz 接入向导分批放开',
    enabled: true,
    scope: 'environment',
    updatedAt: '2026-08-25T10:30:00+08:00'
  }
];

export const mockCredentialProviders: CredentialProvider[] = [
  {
    id: 'cp_vault_01',
    provider: 'HashiCorp Vault',
    kind: 'vault-kv-v2',
    status: 'healthy',
    secretCount: 14,
    lastRotatedAt: '2026-08-20T03:00:00+08:00'
  },
  {
    id: 'cp_kms_01',
    provider: 'Cloud KMS',
    kind: 'managed-kms',
    status: 'healthy',
    secretCount: 6,
    lastRotatedAt: '2026-08-18T03:00:00+08:00'
  },
  {
    id: 'cp_env_01',
    provider: 'Environment Variables（遗留）',
    kind: 'env',
    status: 'degraded',
    secretCount: 3,
    lastRotatedAt: '2026-07-30T10:00:00+08:00'
  }
];

export const mockNotificationRules: NotificationRule[] = [
  {
    id: 'nr_001',
    event: 'budget.warning_threshold',
    channel: 'slack',
    target: '#zebra-ops',
    enabled: true
  },
  {
    id: 'nr_002',
    event: 'effect.uncertain_created',
    channel: 'webhook',
    target: 'https://hooks.zebra.local/effect-uncertain',
    enabled: true
  },
  {
    id: 'nr_003',
    event: 'conformance.failed',
    channel: 'email',
    target: 'platform-team@zebra.local',
    enabled: true
  },
  {
    id: 'nr_004',
    event: 'provider.outage',
    channel: 'slack',
    target: '#zebra-critical',
    enabled: true
  },
  {
    id: 'nr_005',
    event: 'client_effect.backlog',
    channel: 'webhook',
    target: 'https://hooks.zebra.local/client-backlog',
    enabled: false
  }
];

export const mockHealthChecks: PlatformHealthCheck[] = [
  {
    name: 'PostgreSQL 主库',
    component: 'storage',
    status: 'healthy',
    latencyMs: 4,
    detail: 'replication lag 120ms',
    checkedAt: '2026-08-26T09:44:00+08:00'
  },
  {
    name: 'Redis Live Stream',
    component: 'acceleration',
    status: 'healthy',
    latencyMs: 1,
    detail: 'stream backlog 0',
    checkedAt: '2026-08-26T09:44:00+08:00'
  },
  {
    name: 'Worker Fleet',
    component: 'runtime',
    status: 'degraded',
    latencyMs: 12,
    detail: 'wrk-b-04 offline（计划内缩容）',
    checkedAt: '2026-08-26T09:44:00+08:00'
  },
  {
    name: 'Sandbox 供给池',
    component: 'runtime',
    status: 'healthy',
    latencyMs: 88,
    detail: 'warm pool 24 可用',
    checkedAt: '2026-08-26T09:44:00+08:00'
  },
  {
    name: 'DeepSeek Provider',
    component: 'model-provider',
    status: 'healthy',
    latencyMs: 320,
    detail: '429 率 0.2%（过去 1h）',
    checkedAt: '2026-08-26T09:44:00+08:00'
  },
  {
    name: 'Host Connector（trench）',
    component: 'integration',
    status: 'healthy',
    latencyMs: 45,
    detail: 'TLS 证书 60 天后到期',
    checkedAt: '2026-08-26T09:44:00+08:00'
  },
  {
    name: 'Host Connector（fake-host-b）',
    component: 'integration',
    status: 'down',
    latencyMs: 10000,
    detail: 'JWKS 证书过期，连接失败',
    checkedAt: '2026-08-26T09:44:00+08:00'
  }
];
