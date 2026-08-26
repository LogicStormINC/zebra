import type { Metadata } from 'next';

import { PageHeader } from '@/components/platform/page-header';
import { EmptyState } from '@/components/platform/empty-state';
import { repository } from '@/lib/platform/repository';
import { TrustTable } from '@/features/integrations/components/trust-table';

export const metadata: Metadata = {
  title: '入站信任'
};

/** 入站信任列表页（PRD 13）。 */
export default function TrustPage() {
  const trusts = repository.trusts();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='入站信任'
        description='Host 到平台的身份与授权验证配置：Issuer / Audience / JWKS、来源白名单与命名空间策略；平台不展示完整 Token（PRD 13）'
      />
      {trusts.length === 0 ? (
        <EmptyState title='暂无入站信任配置' description='从接入向导第 2 步开始配置' icon='trust' />
      ) : (
        <div className='flex flex-1 flex-col p-4 md:px-6'>
          <TrustTable trusts={trusts} />
        </div>
      )}
    </div>
  );
}
