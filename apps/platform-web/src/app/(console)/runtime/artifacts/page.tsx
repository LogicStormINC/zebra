import { PageHeader } from '@/components/platform/page-header';
import { ArtifactsList } from '@/features/runtime/components/artifacts-list';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Artifacts'
};

export default function ArtifactsPage() {
  const artifacts = [...repository.artifacts()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Artifacts'
        description='Task 产物存档：报告、补丁、导出与诊断包，按 digest 校验下载'
      />
      <div className='p-4 md:px-6'>
        <ArtifactsList artifacts={artifacts} />
      </div>
    </div>
  );
}
