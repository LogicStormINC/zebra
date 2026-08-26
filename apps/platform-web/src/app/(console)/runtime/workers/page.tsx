import { PageHeader } from '@/components/platform/page-header';
import { WorkersGrid } from '@/features/runtime/components/workers-grid';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Workers'
};

export default function WorkersPage() {
  const workers = repository.workers();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Workers'
        description='无状态 harness worker 池：区域、沙箱等级、任务水位、资源占用与心跳租约'
      />
      <div className='p-4 md:px-6'>
        <WorkersGrid workers={workers} />
      </div>
    </div>
  );
}
