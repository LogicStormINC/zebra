'use client';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnFiltersState,
  type RowSelectionState,
  type SortingState,
  type VisibilityState
} from '@tanstack/react-table';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/ui/table/data-table';
import { DataTableToolbar } from '@/components/ui/table/data-table-toolbar';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { createTaskColumns } from './task-table-columns';
import type { Task } from '@/lib/platform/types';

/** 终态 Task（PRD 17.4）：批量取消仅允许作用于非终态行。 */
const TERMINAL_STATUSES: ReadonlySet<Task['status']> = new Set(['completed', 'failed', 'cancelled']);

/** Task 列表（PRD 17）：TanStack 客户端表格 + 筛选 + 导出 + 批量取消。 */
export function TasksTable({ tasks }: { tasks: Task[] }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'createdAt', desc: true }]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  // Wait Reason / Has Subagent 列默认收进 View Options，筛选仍可在工具栏使用
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({
    waitReason: false,
    hasSubagent: false
  });

  const columns = useMemo(
    () =>
      createTaskColumns({
        hosts: tasks.map((task) => task.hostAppId),
        namespaces: tasks.map((task) => task.namespace),
        agents: tasks.map((task) => task.agentName),
        waitReasons: tasks
          .map((task) => task.waitReason)
          .filter((reason): reason is string => typeof reason === 'string')
      }),
    [tasks]
  );

  // oxlint-disable-next-line react/incompatible-library -- TanStack Table's useReactTable is incompatible with React Compiler memoization by design; the compiler already skips optimizing this component
  const table = useReactTable({
    data: tasks,
    columns,
    state: { sorting, columnFilters, rowSelection, columnVisibility },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onRowSelectionChange: setRowSelection,
    onColumnVisibilityChange: setColumnVisibility,
    getRowId: (row) => row.id,
    enableRowSelection: true,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues()
  });

  const selectedTasks = table.getFilteredSelectedRowModel().rows.map((row) => row.original);
  const cancellableTasks = selectedTasks.filter((task) => !TERMINAL_STATUSES.has(task.status));
  const allSelectedTerminal = selectedTasks.length > 0 && cancellableTasks.length === 0;

  return (
    <DataTable
      table={table}
      actionBar={
        <div className='border-destructive/30 bg-destructive/5 flex items-center justify-between gap-2 rounded-lg border p-2.5'>
          <p className='text-destructive text-sm'>
            {allSelectedTerminal
              ? `已选择 ${selectedTasks.length} 个 Task，所选 Task 均为终态，仅允许取消非终态 Task。`
              : `已选择 ${selectedTasks.length} 个 Task，其中 ${cancellableTasks.length} 个非终态，可执行批量取消：`}
          </p>
          <RiskConfirmDialog
            trigger={
              <Button variant='destructive' size='sm' disabled={cancellableTasks.length === 0}>
                批量取消
              </Button>
            }
            title={`批量取消 ${cancellableTasks.length} 个非终态 Task`}
            impact='中断所选非终态 Task 的当前 Attempt，通知其 Subagent 停止，未完成 Host Effect 进入对账（终态 Task 不受影响）'
            irreversibility='取消后不可恢复，只能重新创建 Task'
            currentRevision={`${cancellableTasks.length} non-terminal tasks`}
            actionLabel='确认批量取消'
            onConfirm={() => {
              setRowSelection({});
            }}
          />
        </div>
      }
    >
      <DataTableToolbar table={table}>
        <Button
          variant='outline'
          size='sm'
          onClick={() =>
            toast.success('导出已提交（演示）', {
              description: `按当前筛选导出 ${table.getFilteredRowModel().rows.length} 行 CSV`
            })
          }
        >
          导出
        </Button>
      </DataTableToolbar>
    </DataTable>
  );
}
