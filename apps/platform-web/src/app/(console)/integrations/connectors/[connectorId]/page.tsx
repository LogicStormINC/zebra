import type { Metadata } from 'next';

import { repository } from '@/lib/platform/repository';
import {
  ConnectorDetail,
  ConnectorNotFound
} from '@/features/integrations/components/connector-detail';

export const metadata: Metadata = {
  title: 'Connector 详情'
};

/** Connector 详情页（PRD 11）。 */
export default async function ConnectorDetailPage({
  params
}: {
  params: Promise<{ connectorId: string }>;
}) {
  const { connectorId } = await params;
  const connector = repository.connector(connectorId);

  if (!connector) {
    return <ConnectorNotFound connectorId={connectorId} />;
  }

  const bindings = repository.bindings().filter((binding) => binding.hostAppId === connector.hostAppId);
  const auditEntries = repository.auditEntries().filter((entry) => entry.hostAppId === connector.hostAppId);

  return <ConnectorDetail connector={connector} bindings={bindings} auditEntries={auditEntries} />;
}
