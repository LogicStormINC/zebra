import type { Metadata } from 'next';

import { PageHeader } from '@/components/platform/page-header';
import { EmptyState } from '@/components/platform/empty-state';
import { repository } from '@/lib/platform/repository';
import { ConnectorsTable } from '@/features/integrations/components/connectors-table';

export const metadata: Metadata = {
  title: 'Connector'
};

/** Connector 列表页（PRD 11.1）。 */
export default function ConnectorsPage() {
  const connectors = repository.connectors();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Connector'
        description='平台到 Host 的出站通道：端点、协议版本、凭据引用与版本化规则；凭据仅保存引用不落明文（PRD 11）'
      />
      {connectors.length === 0 ? (
        <EmptyState title='暂无 Connector' description='从接入向导第 3 步开始登记' icon='connector' />
      ) : (
        <div className='flex flex-1 flex-col p-4 md:px-6'>
          <ConnectorsTable connectors={connectors} />
        </div>
      )}
    </div>
  );
}
