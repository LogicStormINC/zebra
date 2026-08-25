import { PageHeader } from '@/components/platform/page-header';
import { HostEffectsTable } from '@/features/runtime/components/host-effects-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Host Effects'
};

export default function HostEffectsPage() {
  const effects = [...repository.hostEffects()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Host Effects'
        description='Host 后端派发与其 Receipt 对账：uncertain 项需要执行 Reconcile、标记解决或升级人工'
      />
      <div className='p-4 md:px-6'>
        <HostEffectsTable effects={effects} />
      </div>
    </div>
  );
}
