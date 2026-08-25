import Link from 'next/link';
import { notFound } from 'next/navigation';

import { PageHeader } from '@/components/platform/page-header';
import { ConformanceDetail } from '@/features/quality/components/conformance-detail';
import { repository } from '@/lib/platform/repository';

type PageProps = { params: Promise<{ runId: string }> };

/** Conformance Run 详情页（PRD 16.2）。 */
export default async function ConformanceDetailPage({ params }: PageProps) {
  const { runId } = await params;
  const run = repository.conformanceRun(runId);
  if (!run) notFound();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title={
          <span>
            Conformance Run{' '}
            <span className='text-muted-foreground font-mono text-base font-normal'>{run.id}</span>
          </span>
        }
        description={`${run.hostAppId} · ${run.environment} · ${run.surface === 'backend' ? 'Backend' : 'Frontend'} Surface 的验收检查明细`}
        meta={
          <>
            <Link href='/quality/conformance' className='text-primary hover:underline'>
              返回列表
            </Link>
          </>
        }
      />
      <div className='p-4 md:px-6'>
        <ConformanceDetail run={run} />
      </div>
    </div>
  );
}
