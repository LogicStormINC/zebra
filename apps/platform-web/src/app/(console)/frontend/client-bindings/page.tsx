import { PageHeader } from '@/components/platform/page-header';
import { ClientBindingsTable } from '@/features/frontend/components/client-bindings-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Client Run Binding'
};

/** Client Run Binding 列表页。 */
export default function ClientBindingsPage() {
  const bindings = repository.clientRunBindings();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Client Run Binding'
        description='Task / Run 与 Client Session 的能力快照绑定：绑定内 Profile Digest 与 Snapshot Digest 固定不变'
      />
      <div className='p-4 md:px-6'>
        <ClientBindingsTable bindings={bindings} />
      </div>
    </div>
  );
}
