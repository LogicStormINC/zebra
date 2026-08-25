import { PageHeader } from '@/components/platform/page-header';
import { MountedInspector } from '@/features/frontend/components/mounted-inspector';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Mounted Capability Inspector'
};

/** Mounted Capability Inspector 页（PRD 13.8）。 */
export default function MountedInspectorPage() {
  const snapshots = repository.mountedSnapshots();
  const profiles = repository.frontendProfiles();
  const effects = repository.clientEffects();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Mounted Capability Inspector'
        description='按 Client Session 检查实际挂载的能力快照：漂移检测（Profile Digest / Action / Schema / Origin / Build / UI Revision / Fence）与在线治理操作'
      />
      <div className='p-4 md:px-6'>
        <MountedInspector snapshots={snapshots} profiles={profiles} effects={effects} />
      </div>
    </div>
  );
}
