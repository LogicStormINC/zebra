import { PageHeader } from '@/components/platform/page-header';
import { ReleaseGatesView } from '@/features/quality/components/release-gates-view';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Release Gate'
};

/** Release Gate 分组卡片页。 */
export default function ReleaseGatesPage() {
  const gates = repository.releaseGates();
  const releases = repository.agentReleases();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Release Gate'
        description='按 Agent Release 汇总 Promote 门禁：Conformance、Security Review、Evaluation 与 Canary 指标全部通过才允许推进'
      />
      <div className='p-4 md:px-6'>
        <ReleaseGatesView gates={gates} releases={releases} />
      </div>
    </div>
  );
}
