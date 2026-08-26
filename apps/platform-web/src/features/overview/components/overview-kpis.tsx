'use client';
import { KpiCard } from '@/components/platform/kpi-card';
import { formatNumber, formatUsd } from '@/lib/platform/format';
import { overviewKpis } from '@/lib/platform/mock/overview';

/** KPI 第一行（PRD 9.2）：每个 KPI 支持点击跳转预置筛选列表。 */
export function OverviewKpis() {
  return (
    <div className='grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8'>
      <KpiCard
        label='已接入 Host'
        value={overviewKpis.connectedHosts}
        icon='host'
        href='/integrations/hosts'
        hint='4 个环境分布'
      />
      <KpiCard
        label='已发布 Agent'
        value={overviewKpis.publishedAgents}
        icon='agentRelease'
        href='/agents/releases'
        hint='2 个 Definition'
      />
      <KpiCard
        label='24h Task'
        value={formatNumber(overviewKpis.tasks24h)}
        icon='task'
        href='/runtime/tasks'
      />
      <KpiCard
        label='Task 成功率'
        value={`${(overviewKpis.taskSuccessRate * 100).toFixed(1)}%`}
        tone='success'
        icon='badgeCheck'
        href='/runtime/tasks'
      />
      <KpiCard
        label='等待与阻塞'
        value={overviewKpis.waitingOrBlockedTasks}
        tone='warning'
        icon='clock'
        href='/runtime/tasks'
      />
      <KpiCard
        label='Uncertain Effect'
        value={overviewKpis.uncertainEffects}
        tone={overviewKpis.uncertainEffects > 0 ? 'failure' : 'success'}
        icon='effect'
        href='/runtime/host-effects'
      />
      <KpiCard
        label='今日 Token'
        value={formatNumber(overviewKpis.tokensToday)}
        icon='usage'
        href='/governance/usage'
      />
      <KpiCard
        label='今日成本'
        value={formatUsd(overviewKpis.costTodayUsd)}
        icon='billing'
        href='/governance/usage'
      />
    </div>
  );
}
