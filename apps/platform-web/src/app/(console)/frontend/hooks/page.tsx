import { PageHeader } from '@/components/platform/page-header';
import { HooksContractView } from '@/features/frontend/components/hooks-contract-view';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Hook Contract'
};

/** Hook Contract 页（PRD 13.7）。 */
export default function FrontendHooksPage() {
  const profiles = repository.frontendProfiles();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Hook Contract'
        description='按 Frontend Profile 生成 React / Next.js / CopilotKit 接入示例：仅包含 Contract Name、Schema 与 Provider 配置，不生成业务 Handler 实现'
      />
      <div className='p-4 md:px-6'>
        <HooksContractView profiles={profiles} />
      </div>
    </div>
  );
}
