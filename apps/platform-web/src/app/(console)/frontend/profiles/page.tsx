import { PageHeader } from '@/components/platform/page-header';
import { FrontendProfilesTable } from '@/features/frontend/components/frontend-profiles-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Frontend Profile'
};

/** Frontend Profile 列表页（PRD 13.2）。 */
export default function FrontendProfilesPage() {
  const profiles = repository.frontendProfiles();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Frontend Profile'
        description='声明式前端能力契约：Readables / Actions / Components / Origins 与 Build、版本与 Conformance 状态'
      />
      <div className='p-4 md:px-6'>
        <FrontendProfilesTable profiles={profiles} />
      </div>
    </div>
  );
}
