import { PageHeader } from '@/components/platform/page-header';
import { SecurityFindings } from '@/features/governance/components/security-findings';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Security Findings'
};

export default function GovernanceSecurityPage() {
  const findings = repository.securityFindings();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Security Findings'
        description='安全发现与处置（Trust / Grant / Effect 维度）：按 Severity 分级跟踪状态流转'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <SecurityFindings findings={findings} />
      </div>
    </div>
  );
}
