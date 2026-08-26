import { PageHeader } from '@/components/platform/page-header';
import { EvaluationsView } from '@/features/quality/components/evaluations-view';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Evaluation'
};

/** Evaluation 列表页。 */
export default function EvaluationsPage() {
  const evaluations = repository.evaluations();
  const releases = repository.agentReleases();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Evaluation'
        description='Agent Release 的 Golden Dataset 评估：质量分、工具准确率、结构化输出通过率、延迟与成本，点击行查看指标详情'
      />
      <div className='p-4 md:px-6'>
        <EvaluationsView evaluations={evaluations} releases={releases} />
      </div>
    </div>
  );
}
