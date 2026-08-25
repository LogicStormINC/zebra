import { PageHeader } from '@/components/platform/page-header';
import { RolloutsView } from '@/features/quality/components/rollouts-view';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Rollout'
};

/** Rollout 列表页（PRD 24）。 */
export default function RolloutsPage() {
  const rollouts = repository.rollouts();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Rollout'
        description='发布对象的灰度推进：dry-run → canary-5/25/50 → production，每一步由 Release Gates 守门，支持按版本回滚'
      />
      <div className='p-4 md:px-6'>
        <RolloutsView rollouts={rollouts} />
      </div>
    </div>
  );
}
