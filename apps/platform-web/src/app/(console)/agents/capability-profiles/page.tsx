import { PageHeader } from '@/components/platform/page-header';
import { CapabilityProfilesList } from '@/features/agents/components/capability-profiles-list';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Capability Profiles'
};

export default function CapabilityProfilesPage() {
  const profiles = repository.capabilityProfiles();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Capability Profiles'
        description='能力档案：backendTools / clientActions / readables 三组能力的版本化定义，被 Agent Definition 引用'
      />
      <div className='p-4 md:px-6'>
        <CapabilityProfilesList profiles={profiles} />
      </div>
    </div>
  );
}
