import { PageHeader } from '@/components/platform/page-header';
import { SubagentsList } from '@/features/runtime/components/subagents-list';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Subagents'
};

export default function SubagentsPage() {
  const links = repository.subagentLinks();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Subagents'
        description='Durable Subagent：子任务是独立的持久 Task，崩溃后由父 Task 按 wakeup policy 重新挂接，不依赖进程内存。'
      />
      <div className='p-4 md:px-6'>
        <SubagentsList links={links} />
      </div>
    </div>
  );
}
