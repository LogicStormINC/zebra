import type { Metadata } from 'next';

import { repository } from '@/lib/platform/repository';
import { HostDetail } from '@/features/integrations/components/host-detail';
import { HostNotFound } from '@/features/integrations/components/host-overview-tab';

export const metadata: Metadata = {
  title: 'Host 详情'
};

/** Host 详情页（PRD 10.2）。 */
export default async function HostDetailPage({
  params
}: {
  params: Promise<{ hostId: string }>;
}) {
  const { hostId } = await params;
  const host = repository.host(hostId);

  if (!host) {
    return <HostNotFound hostId={hostId} />;
  }

  const trust = repository.trusts().find((item) => item.hostAppId === host.appId);
  const connector = host.connectorId ? repository.connector(host.connectorId) : undefined;
  const manifest = host.manifestId ? repository.manifest(host.manifestId) : undefined;
  const frontendProfile = host.frontendProfileId
    ? repository.frontendProfile(host.frontendProfileId)
    : undefined;
  const bindings = repository.bindings().filter((binding) => binding.hostAppId === host.appId);
  const conformanceRuns = repository
    .conformanceRuns()
    .filter((run) => run.hostAppId === host.appId);
  const auditEntries = repository.auditEntries().filter((entry) => entry.hostAppId === host.appId);
  const tasks = repository.tasks().filter((task) => task.hostAppId === host.appId);
  const clientSessions = repository
    .clientSessions()
    .filter((session) => session.hostAppId === host.appId);
  const usage = repository.usage().filter((record) => record.hostAppId === host.appId);
  const releaseNames = Object.fromEntries(
    repository.agentReleases().map((release) => [release.id, release.definitionName])
  );

  return (
    <HostDetail
      host={host}
      trust={trust}
      connector={connector}
      manifest={manifest}
      frontendProfile={frontendProfile}
      bindings={bindings}
      conformanceRuns={conformanceRuns}
      auditEntries={auditEntries}
      tasks={tasks}
      clientSessions={clientSessions}
      usage={usage}
      releaseNames={releaseNames}
    />
  );
}
