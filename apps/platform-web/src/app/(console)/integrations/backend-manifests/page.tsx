import type { Metadata } from 'next';

import { PageHeader } from '@/components/platform/page-header';
import { EmptyState } from '@/components/platform/empty-state';
import { repository } from '@/lib/platform/repository';
import { ManifestsTable } from '@/features/integrations/components/manifests-table';

export const metadata: Metadata = {
  title: 'Backend Manifest'
};

/** Backend Manifest 列表页（PRD 12.1）。 */
export default function BackendManifestsPage() {
  const manifests = repository.manifests();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Backend Manifest'
        description='Host 后端能力契约：Tool、Grant Scope、风险分级、幂等与对账声明；Revision 不可变，修改即新版本（PRD 12）'
      />
      {manifests.length === 0 ? (
        <EmptyState title='暂无 Backend Manifest' description='从接入向导第 4 步开始提交' icon='manifest' />
      ) : (
        <div className='flex flex-1 flex-col p-4 md:px-6'>
          <ManifestsTable manifests={manifests} />
        </div>
      )}
    </div>
  );
}
