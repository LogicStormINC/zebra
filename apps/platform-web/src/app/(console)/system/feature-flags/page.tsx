import { PageHeader } from '@/components/platform/page-header';
import { FeatureFlagTable } from '@/features/system/components/feature-flag-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Feature Flag'
};

export default function SystemFeatureFlagsPage() {
  const flags = repository.featureFlags();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Feature Flag'
        description='平台功能开关（PRD 14.3）：按作用域控制能力灰度，变更实时生效并记录审计'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <FeatureFlagTable flags={flags} />
      </div>
    </div>
  );
}
