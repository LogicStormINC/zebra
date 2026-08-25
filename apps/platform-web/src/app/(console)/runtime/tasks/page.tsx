import { PageHeader } from '@/components/platform/page-header';
import { TasksTable } from '@/features/runtime/components/tasks-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Tasks'
};

export default function RuntimeTasksPage() {
  const tasks = repository.tasks();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Tasks'
        description='全部 Task 的运行视图：状态、等待原因、编排、Token 与成本；支持筛选、导出与批量取消'
      />
      <div className='flex flex-1 flex-col p-4 md:px-6'>
        <TasksTable tasks={tasks} />
      </div>
    </div>
  );
}
