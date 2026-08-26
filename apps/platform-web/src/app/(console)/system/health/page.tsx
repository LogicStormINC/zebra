import { PageHeader } from '@/components/platform/page-header';
import { HealthView } from '@/features/system/components/health-view';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Platform Health'
};

export default function SystemHealthPage() {
  const checks = repository.healthChecks();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Platform Health'
        description='平台健康（PRD 30）：组件分组检查与依赖状态，降级项按 fail closed 处理'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <HealthView checks={checks} />
      </div>
    </div>
  );
}
