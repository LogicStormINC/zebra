import type {
  AuditEntry,
  Quota,
  ReconciliationEntry,
  SecurityFinding,
  UsageRecord
} from '@/lib/platform/types';

/** 治理与审计 mock 数据：Quota、Usage、Audit、Security Finding、Reconciliation。 */

export const mockQuotas: Quota[] = [
  {
    id: 'q_trench_tokens',
    scope: 'namespace/trench/prod',
    dimension: 'model_tokens',
    softLimit: 8_000_000,
    hardLimit: 10_000_000,
    warningThresholdPct: 80,
    used: 6_420_000,
    resetCycle: 'monthly',
    updatedAt: '2026-08-26T08:00:00+08:00'
  },
  {
    id: 'q_trench_tasks',
    scope: 'namespace/trench/prod',
    dimension: 'concurrent_tasks',
    softLimit: 8,
    hardLimit: 12,
    warningThresholdPct: 75,
    used: 6,
    resetCycle: 'hourly',
    updatedAt: '2026-08-26T09:00:00+08:00'
  },
  {
    id: 'q_trench_client_actions',
    scope: 'namespace/trench/prod',
    dimension: 'client_actions',
    softLimit: 40_000,
    hardLimit: 50_000,
    warningThresholdPct: 85,
    used: 12_800,
    resetCycle: 'monthly',
    updatedAt: '2026-08-26T08:00:00+08:00'
  },
  {
    id: 'q_jazz_tokens',
    scope: 'namespace/jazz/staging',
    dimension: 'model_tokens',
    softLimit: 1_000_000,
    hardLimit: 2_000_000,
    warningThresholdPct: 80,
    used: 96_000,
    resetCycle: 'monthly',
    updatedAt: '2026-08-26T08:00:00+08:00'
  },
  {
    id: 'q_platform_subagents',
    scope: 'platform/global',
    dimension: 'subagents',
    softLimit: 40,
    hardLimit: 60,
    warningThresholdPct: 80,
    used: 9,
    resetCycle: 'hourly',
    updatedAt: '2026-08-26T09:00:00+08:00'
  }
];

/** 近 14 天用量（3 个 Host）。 */
export const mockUsage: UsageRecord[] = Array.from({ length: 14 }, (_, dayOffset) => {
  const day = 25 - dayOffset;
  const date = `2026-08-${String(Math.max(day, 12)).padStart(2, '0')}`;
  const wave = Math.sin(dayOffset / 2.2) * 0.25 + 1;
  const weekend = dayOffset % 7 === 0 || dayOffset % 7 === 6;
  const scale = weekend ? 0.4 : 1;
  return [
    {
      date,
      hostAppId: 'trench',
      inputTokens: Math.round(640_000 * wave * scale),
      outputTokens: Math.round(120_000 * wave * scale),
      reasoningTokens: Math.round(60_000 * wave * scale),
      modelCostUsd: Number((42 * wave * scale).toFixed(2)),
      runtimeSeconds: Math.round(21_600 * wave * scale),
      toolCalls: Math.round(1_800 * wave * scale),
      clientActions: Math.round(420 * wave * scale),
      taskCount: Math.round(180 * wave * scale),
      successRate: 0.94 + (dayOffset % 3) * 0.015
    },
    {
      date,
      hostAppId: 'fake-host-a',
      inputTokens: Math.round(90_000 * wave * scale),
      outputTokens: Math.round(30_000 * wave * scale),
      reasoningTokens: Math.round(8_000 * wave * scale),
      modelCostUsd: Number((6.2 * wave * scale).toFixed(2)),
      runtimeSeconds: Math.round(7_200 * wave * scale),
      toolCalls: Math.round(260 * wave * scale),
      clientActions: 0,
      taskCount: Math.round(36 * wave * scale),
      successRate: 0.9 + (dayOffset % 4) * 0.02
    },
    {
      date,
      hostAppId: 'jazz',
      inputTokens: Math.round(12_000 * scale),
      outputTokens: Math.round(4_000 * scale),
      reasoningTokens: 0,
      modelCostUsd: Number((0.8 * scale).toFixed(2)),
      runtimeSeconds: Math.round(900 * scale),
      toolCalls: Math.round(40 * scale),
      clientActions: 0,
      taskCount: Math.round(8 * scale),
      successRate: 1
    }
  ];
}).flat();

export const mockAuditEntries: AuditEntry[] = [
  {
    id: 'aud_20260826_014',
    actor: 'operator:lukeding',
    actorType: 'operator',
    action: 'agent_release.publish',
    resourceType: 'AgentRelease',
    resourceId: 'rel_tr_cr_4',
    environment: 'production',
    hostAppId: 'trench',
    namespace: 'trench/canary',
    beforeDigest: 'aa10ff33cc8841dd…',
    afterDigest: 'bb21aa44dd9950ee…',
    reason: '发布 reviewer prompt 优化与工单摘要改进',
    result: 'succeeded',
    timestamp: '2026-08-26T09:05:00+08:00',
    correlationId: 'corr_a91f'
  },
  {
    id: 'aud_20260826_013',
    actor: 'operator:runtime-ops',
    actorType: 'operator',
    action: 'task.cancel',
    resourceType: 'Task',
    resourceId: 'tsk_01JK2DV6SL',
    environment: 'production',
    hostAppId: 'trench',
    reason: '与结算窗口冲突，改期执行',
    result: 'succeeded',
    timestamp: '2026-08-26T08:58:00+08:00',
    correlationId: 'corr_c55a'
  },
  {
    id: 'aud_20260826_012',
    actor: 'operator:qa',
    actorType: 'operator',
    action: 'connector_binding.rollback',
    resourceType: 'NamespaceBinding',
    resourceId: 'nb_fake_b_dev',
    environment: 'development',
    hostAppId: 'fake-host-b',
    beforeDigest: '4c88ee10cc2b47f0…',
    reason: 'Conformance 失败：connector unreachable',
    result: 'succeeded',
    timestamp: '2026-08-26T08:40:00+08:00',
    correlationId: 'corr_d66b'
  },
  {
    id: 'aud_20260826_011',
    actor: 'operator:security-audit',
    actorType: 'operator',
    action: 'audit.export',
    resourceType: 'AuditExport',
    resourceId: 'exp_202608_02',
    environment: 'production',
    reason: '月度安全审计证据导出',
    result: 'succeeded',
    timestamp: '2026-08-26T08:10:00+08:00',
    correlationId: 'corr_e77c'
  },
  {
    id: 'aud_20260825_010',
    actor: 'operator:lukeding',
    actorType: 'operator',
    action: 'frontend_profile.publish',
    resourceType: 'FrontendProfile',
    resourceId: 'fp_trench_web',
    environment: 'production',
    hostAppId: 'trench',
    afterDigest: 'f1e2d3c4b5a69788…',
    reason: '新增 ui.confirm_escalate human_confirmed Action',
    result: 'succeeded',
    timestamp: '2026-08-25T16:00:00+08:00',
    correlationId: 'corr_f88d'
  },
  {
    id: 'aud_20260825_009',
    actor: 'operator:runtime-ops',
    actorType: 'operator',
    action: 'client_controller.release',
    resourceType: 'ClientSession',
    resourceId: 'cs_6c08',
    environment: 'production',
    hostAppId: 'trench',
    reason: 'Controller 心跳超时，释放 Lease',
    result: 'succeeded',
    timestamp: '2026-08-25T19:20:00+08:00',
    correlationId: 'corr_g99e'
  },
  {
    id: 'aud_20260825_008',
    actor: 'system:reconciler',
    actorType: 'system',
    action: 'effect.reconcile',
    resourceType: 'HostEffect',
    resourceId: 'hfx_01HA6',
    environment: 'development',
    hostAppId: 'fake-host-b',
    reason: 'uncertain effect 自动对账第 2 次：仍未获得 Receipt',
    result: 'failed',
    timestamp: '2026-08-25T18:00:00+08:00',
    correlationId: 'corr_h10f'
  },
  {
    id: 'aud_20260825_007',
    actor: 'operator:jazz-integrator',
    actorType: 'operator',
    action: 'host.register',
    resourceType: 'Host',
    resourceId: 'host_01H9JAZZ00',
    environment: 'staging',
    hostAppId: 'jazz',
    reason: 'Jazz 内容平台启动接入（PRD 5.1 第二业务）',
    result: 'succeeded',
    timestamp: '2026-08-25T10:40:00+08:00',
    correlationId: 'corr_i21a'
  },
  {
    id: 'aud_20260825_006',
    actor: 'operator:lukeding',
    actorType: 'operator',
    action: 'quota.update',
    resourceType: 'Quota',
    resourceId: 'q_trench_tokens',
    environment: 'production',
    reason: '8 月活动期临时上调 soft limit 至 8M',
    result: 'succeeded',
    timestamp: '2026-08-25T09:30:00+08:00',
    correlationId: 'corr_j32b'
  },
  {
    id: 'aud_20260824_005',
    actor: 'operator:lukeding',
    actorType: 'operator',
    action: 'backend_manifest.publish',
    resourceType: 'BackendManifest',
    resourceId: 'bm_trench_v5',
    environment: 'production',
    hostAppId: 'trench',
    afterDigest: 'be55cc3a118d40ee…',
    reason: '新增 trench.update_ticket_status 写工具',
    result: 'succeeded',
    timestamp: '2026-08-24T10:00:00+08:00',
    correlationId: 'corr_k43c'
  },
  {
    id: 'aud_20260824_004',
    actor: 'agent:trench-code-reviewer',
    actorType: 'agent',
    action: 'write.denied',
    resourceType: 'HostTool',
    resourceId: 'trench.update_ticket_status',
    environment: 'production',
    hostAppId: 'trench',
    reason: 'HostGrant scope 不含 trench.tickets:write（fail closed）',
    result: 'denied',
    timestamp: '2026-08-24T15:12:00+08:00',
    correlationId: 'corr_l54d'
  },
  {
    id: 'aud_20260824_003',
    actor: 'operator:lukeding',
    actorType: 'operator',
    action: 'host.suspend',
    resourceType: 'Host',
    resourceId: 'host_01HFAKEB00',
    environment: 'development',
    hostAppId: 'fake-host-b',
    reason: 'Trust invalid：JWKS 证书过期，暂停接入',
    result: 'succeeded',
    timestamp: '2026-08-23T10:00:00+08:00',
    correlationId: 'corr_m65e'
  }
];

export const mockSecurityFindings: SecurityFinding[] = [
  {
    id: 'sf_004',
    severity: 'high',
    title: 'fake-host-b JWKS 证书过期',
    resource: 'trust_fake_b_01',
    description: 'JWKS 端点证书已于 2026-08-22 过期，Grant 校验 fail closed，Host 接入已暂停。',
    recommendation: '业务侧轮换证书后重新发布 Trust Revision；平台已自动阻断该 Host 新 Task。',
    status: 'open',
    detectedAt: '2026-08-23T09:50:00+08:00'
  },
  {
    id: 'sf_003',
    severity: 'medium',
    title: 'Uncertain Effect 超过 24h 未收敛',
    resource: 'hfx_01HA6',
    description: 'fake_b.write_marker 调用超时后进入 uncertain，两次自动对账未获得 Receipt。',
    recommendation: '人工核对 fake-host-b 业务侧写入状态后标记已解决或回滚。',
    status: 'acknowledged',
    detectedAt: '2026-08-25T18:05:00+08:00'
  },
  {
    id: 'sf_002',
    severity: 'low',
    title: 'Client Effect stale_ui_state 占比升高',
    resource: 'fp_trench_web',
    description: 'trw-20260823-2 构建存在 UI Revision 滞后窗口，产生 3 个 stale effect。',
    recommendation: '升级到 trw-20260824-3 后观察；Hook 已在 9.2 修复。',
    status: 'mitigated',
    detectedAt: '2026-08-25T19:30:00+08:00'
  },
  {
    id: 'sf_001',
    severity: 'critical',
    title: '测试 Grant 误携带生产 scope（演练）',
    resource: 'dry_20260820_00',
    description: 'Dry Run 生成的受限 Grant 曾误携带 trench.tickets:write；策略引擎已拒绝。',
    recommendation: '保持 Dry Run namespace 隔离；已加入 Conformance 断言。',
    status: 'resolved',
    detectedAt: '2026-08-20T11:00:00+08:00'
  }
];

export const mockReconciliation: ReconciliationEntry[] = [
  {
    id: 'rec_0206',
    dispatchId: 'hfx_01HA6',
    taskId: 'tsk_01JK2KJ8PC',
    hostAppId: 'fake-host-b',
    operation: 'fake_b.write_marker',
    status: 'manual_review',
    lastAttempt: '2026-08-25T18:00:00+08:00',
    attempts: 2
  },
  {
    id: 'rec_0205',
    dispatchId: 'hfx_01HA4',
    taskId: 'tsk_01JK2J7WNA',
    hostAppId: 'trench',
    operation: 'trench.get_position',
    status: 'matched',
    lastAttempt: '2026-08-25T10:19:00+08:00',
    attempts: 1
  },
  {
    id: 'rec_0204',
    dispatchId: 'hfx_01HA5',
    taskId: 'tsk_01JK2M4Q8T',
    hostAppId: 'trench',
    operation: 'trench.get_risk_report',
    status: 'matched',
    lastAttempt: '2026-08-26T09:20:14+08:00',
    attempts: 1
  }
];
