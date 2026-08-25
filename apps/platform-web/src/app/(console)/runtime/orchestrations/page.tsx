import { PageHeader } from '@/components/platform/page-header';
import { OrchestrationsList } from '@/features/runtime/components/orchestrations-list';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Orchestrations'
};

export default function OrchestrationsPage() {
  const runs = repository.orchestrations();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Orchestrations'
        description='编排运行：DAG 计划、节点状态、completion gate 与编排级 Token / 成本'
      />
      <div className='p-4 md:px-6'>
        <OrchestrationsList runs={runs} />
      </div>
    </div>
  );
}
