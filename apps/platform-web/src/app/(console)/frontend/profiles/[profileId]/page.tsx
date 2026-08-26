import Link from 'next/link';
import { notFound } from 'next/navigation';

import { PageHeader } from '@/components/platform/page-header';
import { FrontendProfileDetail } from '@/features/frontend/components/frontend-profile-detail';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

type PageProps = { params: Promise<{ profileId: string }> };

/** Frontend Profile 详情页（PRD 13.3–13.6 / 13.8）。 */
export default async function FrontendProfileDetailPage({ params }: PageProps) {
  const { profileId } = await params;
  const profile = repository.frontendProfile(profileId);
  if (!profile) notFound();

  const digestPrefix = profile.digest.slice(0, 8);
  const snapshots = repository.mountedSnapshots().filter(
    (snapshot) => snapshot.profileDigest.slice(0, 8) === digestPrefix
  );
  const conformanceRuns = repository
    .conformanceRuns()
    .filter((run) => run.hostAppId === profile.hostAppId && run.surface === 'frontend');
  const audits = repository.auditEntries().filter((entry) => entry.resourceId === profile.id);
  const policy =
    repository.policies().find((item) => item.scope === `frontend-profile/${profile.id}`) ?? null;

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title={
          <span>
            {profile.frontendAppId}{' '}
            <span className='text-muted-foreground font-normal'>· Frontend Profile</span>
          </span>
        }
        description={`${profile.hostAppId} 的前端能力契约：Readables / Actions / Components 与 Build、版本、质量状态`}
        meta={
          <>
            <span className='font-mono'>rev {profile.revision}</span>
            <span className='font-mono'>digest {profile.digest.slice(0, 16)}…</span>
            <span className='font-mono'>build {profile.buildId}</span>
            <Link href='/frontend/profiles' className='text-primary hover:underline'>
              返回列表
            </Link>
          </>
        }
      />
      <div className='p-4 md:px-6'>
        <FrontendProfileDetail
          profile={profile}
          snapshots={snapshots}
          conformanceRuns={conformanceRuns}
          audits={audits}
          policy={policy}
        />
      </div>
    </div>
  );
}
