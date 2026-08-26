import { mockUsage } from './governance';

/** 平台总览聚合数据（PRD 9.2）。 */

export const overviewKpis = {
  connectedHosts: 4,
  publishedAgents: 5,
  tasks24h: 294,
  taskSuccessRate: 0.938,
  waitingOrBlockedTasks: 6,
  uncertainEffects: 1,
  tokensToday: 742_300,
  costTodayUsd: 48.6
};

export function overviewTrend(days = 14) {
  return mockUsage
    .filter((record) => record.hostAppId === 'trench' || record.hostAppId === 'fake-host-a')
    .slice(0, days * 2)
    .reduce<{ date: string; tasks: number; successRate: number; tokens: number; costUsd: number }[]>(
      (acc, record) => {
        const existing = acc.find((item) => item.date === record.date);
        if (existing) {
          existing.tasks += record.taskCount;
          existing.tokens += record.inputTokens + record.outputTokens;
          existing.costUsd = Number((existing.costUsd + record.modelCostUsd).toFixed(2));
          existing.successRate = Number(
            ((existing.successRate + record.successRate) / 2).toFixed(3)
          );
        } else {
          acc.push({
            date: record.date.slice(5),
            tasks: record.taskCount,
            successRate: record.successRate,
            tokens: record.inputTokens + record.outputTokens,
            costUsd: record.modelCostUsd
          });
        }
        return acc;
      },
      []
    )
    .reverse();
}

export const overviewAlerts = [
  {
    id: 'al_003',
    severity: 'high' as const,
    title: 'Uncertain Effect 未收敛',
    detail: 'fake_b.write_marker 超时未对账（hfx_01HA6）',
    href: '/runtime/tasks/tsk_01JK2KJ8PC'
  },
  {
    id: 'al_002',
    severity: 'medium' as const,
    title: 'Frontend Conformance 失败',
    detail: 'hook.unmount_cleanup 未通过，fp_trench_web rev4 Canary 被阻断',
    href: '/quality/conformance/conf_20260826_02'
  },
  {
    id: 'al_001',
    severity: 'low' as const,
    title: 'Host fake-host-b Trust invalid',
    detail: 'JWKS 证书过期，接入已暂停',
    href: '/integrations/hosts/host_01HFAKEB00'
  }
];

export const overviewRecentReleases = [
  { id: 'rel_tr_cr_4', name: 'trench-code-reviewer v4', status: 'canary' as const, at: '2026-08-26T09:05:00+08:00' },
  { id: 'fp_trench_web', name: 'fp_trench_web rev4', status: 'blocked' as const, at: '2026-08-25T16:00:00+08:00' },
  { id: 'bm_trench_v5', name: 'bm_trench_v5', status: 'published' as const, at: '2026-08-24T10:00:00+08:00' },
  { id: 'rel_tr_research_2', name: 'trench-market-research v2', status: 'published' as const, at: '2026-08-24T18:00:00+08:00' }
];

export const overviewRecentHosts = [
  { id: 'host_01H9JAZZ00', name: 'Jazz 内容平台', step: 4, at: '2026-08-25T10:40:00+08:00' },
  { id: 'host_01H9TRENCH', name: 'Trench 交易平台', step: 7, at: '2026-08-25T16:40:00+08:00' },
  { id: 'host_01HFAKEA00', name: 'Fake Host A（验收）', step: 7, at: '2026-08-24T09:10:00+08:00' }
];

export const overviewPendingApprovals = [
  { id: 'apr_0201', type: 'approval' as const, title: 'trench.update_ticket_status（高风险写）', at: '2026-08-26T08:52:00+08:00' },
  { id: 'clr_0181', type: 'clarification' as const, title: '日报是否覆盖衍生品持仓', at: '2026-08-26T07:45:00+08:00' }
];
