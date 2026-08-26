import { PageHeader } from '@/components/platform/page-header';
import { OverviewKpis } from '@/features/overview/components/overview-kpis';
import { OverviewCharts } from '@/features/overview/components/overview-charts';
import { OverviewLists } from '@/features/overview/components/overview-lists';
import { OverviewEmptyState } from '@/features/overview/components/overview-empty-state';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '平台总览'
};

export default function OverviewPage() {
  const tasks = repository.tasks();
  const hosts = repository.hosts();
  const isEmpty = hosts.length === 0;

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='平台总览'
        description='接入规模、运行质量、安全风险与成本状态（数据每 30 秒刷新）'
      />
      {isEmpty ? (
        <OverviewEmptyState />
      ) : (
        <div className='flex flex-col gap-6 p-4 md:px-6'>
          <OverviewKpis />
          <OverviewCharts />
          <OverviewLists
            pendingApprovalCount={tasks.filter((task) => task.status.startsWith('waiting_')).length}
          />
        </div>
      )}
    </div>
  );
}
