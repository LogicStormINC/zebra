import { PageHeader } from '@/components/platform/page-header';
import { UsageView } from '@/features/governance/components/usage-view';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Usage 与成本'
};

export default function GovernanceUsagePage() {
  const usage = repository.usage();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Usage 与成本'
        description='Token、成本与运行用量分析（PRD 22）：按 Host 维度聚合，支持 CSV 导出（导出动作被审计）'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <UsageView usage={usage} />
      </div>
    </div>
  );
}
