import { PageHeader } from '@/components/platform/page-header';
import { CredentialTable } from '@/features/system/components/credential-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Credential Provider'
};

export default function SystemCredentialsPage() {
  const providers = repository.credentialProviders();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Credential Provider'
        description='凭据引用与元数据管理（PRD 6.5）：rotation 与 health 状态，不接触明文 Secret'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <CredentialTable providers={providers} />
      </div>
    </div>
  );
}
