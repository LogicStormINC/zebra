import { PageHeader } from '@/components/platform/page-header';
import { ClientEffectsTable } from '@/features/frontend/components/client-effects-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Client Effect'
};

/** Client Effect 列表页（PRD 20）。 */
export default function ClientEffectsPage() {
  const effects = repository.clientEffects();
  const bindings = repository.clientRunBindings();
  const profiles = repository.frontendProfiles();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Client Effect'
        description='Agent 对前端的受控影响：一次一效（Fence）、UI Revision 校验与 Receipt 回执；详情只展示摘要，不显示原始 Fence Token'
      />
      <div className='p-4 md:px-6'>
        <ClientEffectsTable effects={effects} bindings={bindings} profiles={profiles} />
      </div>
    </div>
  );
}
