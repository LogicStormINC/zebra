import { PageHeader } from '@/components/platform/page-header';
import { ConformanceTable } from '@/features/quality/components/conformance-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Conformance Run'
};

/** Conformance 列表页（PRD 16.1）。 */
export default function ConformancePage() {
  const runs = repository.conformanceRuns();
  const hostOptions = Array.from(new Set(runs.map((run) => run.hostAppId)));

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Conformance Run'
        description='Host 接入标准验收：Backend 与 Frontend 两个 Surface 的 schema、鉴权、幂等、超时、对账等一致性检查'
      />
      <div className='p-4 md:px-6'>
        <ConformanceTable runs={runs} hostOptions={hostOptions} />
      </div>
    </div>
  );
}
