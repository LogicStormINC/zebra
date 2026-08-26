import { PageHeader } from '@/components/platform/page-header';
import { EnvironmentCards } from '@/features/system/components/environment-cards';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Environment'
};

export default function SystemEnvironmentsPage() {
  const environments = repository.environments();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Environment'
        description='环境注册表（PRD 14.1）：Development / Staging / Production 三环境与全局上下文切换'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <EnvironmentCards environments={environments} />
      </div>
    </div>
  );
}
