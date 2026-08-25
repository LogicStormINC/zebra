import { PageHeader } from '@/components/platform/page-header';
import { DryRunsView } from '@/features/quality/components/dry-runs-view';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Dry Run'
};

/** Dry Run 列表页。 */
export default function DryRunsPage() {
  const dryRuns = repository.dryRuns();
  const agentReleases = repository.agentReleases();
  const manifests = repository.manifests();
  const frontendProfiles = repository.frontendProfiles();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Dry Run'
        description='在独立 namespace 或测试标记下执行真实读写链路验证：发布组合（Agent Release / Manifest / Frontend Profile）先过 Dry Run 再进入 Rollout'
      />
      <div className='p-4 md:px-6'>
        <DryRunsView
          dryRuns={dryRuns}
          agentReleases={agentReleases}
          manifests={manifests}
          frontendProfiles={frontendProfiles}
        />
      </div>
    </div>
  );
}
