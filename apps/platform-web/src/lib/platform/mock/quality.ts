import type {
  ConformanceRun,
  DryRun,
  EvaluationRun,
  ReleaseGate,
  Rollout
} from '@/lib/platform/types';

/** 质量与发布 mock 数据。 */

const backendChecks = (host: string) => [
  { name: 'manifest.schema', group: 'Schema', status: 'passed' as const, durationMs: 120 },
  { name: 'auth.jwks_fetch', group: 'Auth', status: 'passed' as const, durationMs: 340 },
  { name: 'auth.grant_scope', group: 'Scope', status: 'passed' as const, durationMs: 210 },
  { name: 'resource.binding_pointer', group: 'Resource', status: 'passed' as const, durationMs: 95 },
  { name: 'namespace.isolation', group: 'Namespace', status: 'passed' as const, durationMs: 180 },
  { name: 'write.idempotency_key', group: 'Idempotency', status: 'passed' as const, durationMs: 150 },
  { name: 'timeout.enforced', group: 'Timeout', status: 'passed' as const, durationMs: 420 },
  { name: 'output.size_bound', group: 'Output Bound', status: 'passed' as const, durationMs: 260 },
  {
    name: 'effect.uncertain_simulation',
    group: 'Uncertain Effect',
    status: 'passed' as const,
    durationMs: 890,
    evidence: `${host} reconcile 端点返回对账证据`
  },
  {
    name: 'reconciliation.round_trip',
    group: 'Reconciliation',
    status: 'passed' as const,
    durationMs: 640
  }
];

export const mockConformanceRuns: ConformanceRun[] = [
  {
    id: 'conf_20260826_01',
    hostAppId: 'trench',
    environment: 'production',
    surface: 'backend',
    profileRevision: 5,
    triggeredBy: 'operator:lukeding',
    startedAt: '2026-08-26T08:30:00+08:00',
    durationMs: 4520,
    passed: 10,
    failed: 0,
    skipped: 0,
    status: 'passed',
    checks: backendChecks('trench')
  },
  {
    id: 'conf_20260826_02',
    hostAppId: 'trench',
    environment: 'production',
    surface: 'frontend',
    profileRevision: 4,
    triggeredBy: 'schedule:profile-publish',
    startedAt: '2026-08-26T08:00:00+08:00',
    durationMs: 6310,
    passed: 11,
    failed: 1,
    skipped: 1,
    status: 'failed',
    checks: [
      { name: 'profile.schema', group: 'Schema', status: 'passed' as const, durationMs: 90 },
      { name: 'client.origin_check', group: 'Client Fence', status: 'passed' as const, durationMs: 130 },
      { name: 'client.fence_hash', group: 'Client Fence', status: 'passed' as const, durationMs: 150 },
      { name: 'ui.revision_monotonic', group: 'UI Revision', status: 'passed' as const, durationMs: 110 },
      {
        name: 'hook.unmount_cleanup',
        group: 'Unmount',
        status: 'failed' as const,
        durationMs: 980,
        reasonCode: 'E_UNMOUNT_LEAK',
        evidence: 'useZebraReadable 卸载后仍残留一次 on_change 上报'
      },
      { name: 'hook.reconnect_replay', group: 'Reconnect', status: 'passed' as const, durationMs: 720 },
      {
        name: 'effect.replay_after_reconnect',
        group: 'Replay',
        status: 'skipped' as const,
        durationMs: 0,
        reasonCode: 'SKIPPED_DEPENDS_ON_UNMOUNT'
      },
      { name: 'host.zero_branch', group: 'Zero Host Branch', status: 'passed' as const, durationMs: 240 }
    ]
  },
  {
    id: 'conf_20260825_03',
    hostAppId: 'fake-host-b',
    environment: 'development',
    surface: 'backend',
    profileRevision: 1,
    triggeredBy: 'operator:qa',
    startedAt: '2026-08-25T13:00:00+08:00',
    durationMs: 3010,
    passed: 8,
    failed: 2,
    skipped: 0,
    status: 'failed',
    checks: [
      { name: 'manifest.schema', group: 'Schema', status: 'passed' as const, durationMs: 100 },
      { name: 'auth.jwks_fetch', group: 'Auth', status: 'failed' as const, durationMs: 5000, reasonCode: 'E_JWKS_UNREACHABLE', evidence: 'connector 不可达' },
      { name: 'auth.grant_scope', group: 'Scope', status: 'skipped' as const, durationMs: 0, reasonCode: 'SKIPPED_AUTH_FAILED' },
      { name: 'reconciliation.round_trip', group: 'Reconciliation', status: 'failed' as const, durationMs: 2100, reasonCode: 'E_RECONCILE_TIMEOUT', evidence: 'read timeout 10s' }
    ]
  },
  {
    id: 'conf_20260824_04',
    hostAppId: 'jazz',
    environment: 'staging',
    surface: 'backend',
    profileRevision: 1,
    triggeredBy: 'operator:jazz-integrator',
    startedAt: '2026-08-25T11:20:00+08:00',
    durationMs: 2870,
    passed: 9,
    failed: 0,
    skipped: 1,
    status: 'passed',
    checks: backendChecks('jazz').slice(0, 9)
  }
];

export const mockDryRuns: DryRun[] = [
  {
    id: 'dry_20260826_02',
    taskId: 'tsk_01JK2BS2QJ',
    hostAppId: 'jazz',
    agentReleaseId: 'rel_gen_exec_2',
    namespace: 'jazz/dry-run',
    result: 'running',
    summary: '验证 jazz.list_drafts 读链路（测试 Grant + 测试 Resource Ref）',
    createdAt: '2026-08-26T09:35:00+08:00'
  },
  {
    id: 'dry_20260825_01',
    taskId: 'tsk_01JK2KQ2RD',
    hostAppId: 'fake-host-a',
    agentReleaseId: 'rel_gen_exec_2',
    namespace: 'fake-a/dry-run',
    result: 'passed',
    summary: 'fake_a.write_marker 幂等键重放一致，零生产写入',
    createdAt: '2026-08-25T14:30:00+08:00'
  }
];

export const mockRollouts: Rollout[] = [
  {
    id: 'ro_0551',
    target: 'agent-release',
    targetId: 'rel_tr_cr_4',
    fromRevision: 3,
    toRevision: 4,
    strategy: 'canary-5',
    gates: [
      { name: 'Conformance Passed', status: 'passed' },
      { name: 'Security Review', status: 'passed' },
      { name: 'Error Rate < 1%', status: 'passed' },
      { name: 'P95 Latency < 8s', status: 'passed' },
      { name: 'Client Effect Failure < 2%', status: 'pending' }
    ],
    status: 'in-progress',
    updatedAt: '2026-08-26T09:00:00+08:00'
  },
  {
    id: 'ro_0550',
    target: 'frontend-profile',
    targetId: 'fp_trench_web',
    fromRevision: 3,
    toRevision: 4,
    strategy: 'canary-25',
    gates: [
      { name: 'Conformance Passed', status: 'failed' },
      { name: 'Client Effect Failure < 2%', status: 'not_required' }
    ],
    status: 'blocked',
    updatedAt: '2026-08-26T08:10:00+08:00'
  },
  {
    id: 'ro_0549',
    target: 'backend-manifest',
    targetId: 'bm_trench_v5',
    fromRevision: 4,
    toRevision: 5,
    strategy: 'production',
    gates: [
      { name: 'Conformance Passed', status: 'passed' },
      { name: 'Security Review', status: 'passed' },
      { name: 'Uncertain Effect Rate < 0.1%', status: 'passed' }
    ],
    status: 'completed',
    updatedAt: '2026-08-24T10:00:00+08:00'
  },
  {
    id: 'ro_0548',
    target: 'connector-binding',
    targetId: 'nb_fake_b_dev',
    fromRevision: 1,
    toRevision: 1,
    strategy: 'rollback',
    gates: [{ name: 'Conformance Passed', status: 'failed' }],
    status: 'rolled-back',
    updatedAt: '2026-08-23T10:00:00+08:00'
  }
];

export const mockEvaluations: EvaluationRun[] = [
  {
    id: 'eval_3391',
    name: 'trench-code-reviewer 回归集',
    agentReleaseId: 'rel_tr_cr_4',
    dataset: 'golden/trench-review-120',
    qualityScore: 0.91,
    toolAccuracy: 0.96,
    structuredOutputPassRate: 0.98,
    latencyP95Ms: 6800,
    costUsdPerRun: 0.29,
    status: 'passed',
    createdAt: '2026-08-25T20:00:00+08:00'
  },
  {
    id: 'eval_3390',
    name: 'trench-market-research 日报质量',
    agentReleaseId: 'rel_tr_research_2',
    dataset: 'golden/daily-report-40',
    qualityScore: 0.84,
    toolAccuracy: 0.9,
    structuredOutputPassRate: 0.93,
    latencyP95Ms: 15400,
    costUsdPerRun: 0.71,
    status: 'passed',
    createdAt: '2026-08-24T21:00:00+08:00'
  },
  {
    id: 'eval_3389',
    name: 'general-executor 沙箱工程集',
    agentReleaseId: 'rel_gen_exec_2',
    dataset: 'golden/swe-bench-lite-50',
    qualityScore: 0.62,
    toolAccuracy: 0.88,
    structuredOutputPassRate: 1.0,
    latencyP95Ms: 41000,
    costUsdPerRun: 1.32,
    status: 'failed',
    createdAt: '2026-08-23T22:00:00+08:00'
  }
];

export const mockReleaseGates: ReleaseGate[] = [
  {
    id: 'gate_rel_tr_cr_4_1',
    releaseId: 'rel_tr_cr_4',
    gate: 'conformance',
    requirement: 'Backend + Frontend Conformance 全部通过',
    status: 'failed',
    evaluatedAt: '2026-08-26T08:15:00+08:00'
  },
  {
    id: 'gate_rel_tr_cr_4_2',
    releaseId: 'rel_tr_cr_4',
    gate: 'security_review',
    requirement: '无 open 状态 Critical/High Security Finding',
    status: 'passed',
    evaluatedAt: '2026-08-25T19:00:00+08:00'
  },
  {
    id: 'gate_rel_tr_cr_4_3',
    releaseId: 'rel_tr_cr_4',
    gate: 'evaluation',
    requirement: '质量分 ≥ 0.85 且无回归',
    status: 'passed',
    evaluatedAt: '2026-08-25T20:00:00+08:00'
  },
  {
    id: 'gate_rel_tr_cr_4_4',
    releaseId: 'rel_tr_cr_4',
    gate: 'canary_metrics',
    requirement: 'Canary 24h：错误率 <1%，Client Effect 失败率 <2%',
    status: 'pending',
    evaluatedAt: '2026-08-26T09:00:00+08:00'
  },
  {
    id: 'gate_rel_gen_exec_2_1',
    releaseId: 'rel_gen_exec_2',
    gate: 'conformance',
    requirement: 'Backend Conformance 全部通过',
    status: 'passed',
    evaluatedAt: '2026-08-23T09:00:00+08:00'
  }
];
