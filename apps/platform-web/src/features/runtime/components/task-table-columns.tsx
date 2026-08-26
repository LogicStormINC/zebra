'use client';
import Link from 'next/link';
import type { ColumnDef, FilterFn } from '@tanstack/react-table';
import { Checkbox } from '@/components/ui/checkbox';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { TASK_STATUS_LABELS, taskStatusTone } from '@/lib/platform/status';
import { formatDateTime, formatNumber, formatUsd, relativeTime } from '@/lib/platform/format';
import type { Task } from '@/lib/platform/types';

/** 多选等值过滤：filter value 为选中值数组，行值命中其一即保留。 */
const includesValue: FilterFn<Task> = (row, columnId, filterValue) => {
  const selected = Array.isArray(filterValue) ? (filterValue as string[]) : [String(filterValue)];
  if (selected.length === 0) return true;
  return selected.includes(String(row.getValue(columnId)));
};

function uniqueOptions(values: string[], labelOf?: (value: string) => string) {
  return [...new Set(values)].map((value) => ({
    value,
    label: labelOf ? labelOf(value) : value
  }));
}

const ALL_STATUSES = Object.keys(TASK_STATUS_LABELS) as (keyof typeof TASK_STATUS_LABELS)[];

/** 无 waitReason 的行统一用 none 参与 multiSelect 过滤。 */
const WAIT_REASON_NONE = 'none';

export function createTaskColumns(input: {
  hosts: string[];
  namespaces: string[];
  agents: string[];
  waitReasons: string[];
}): ColumnDef<Task>[] {
  return [
    {
      id: 'select',
      header: ({ table }) => (
        <Checkbox
          aria-label='全选本页'
          checked={table.getIsAllPageRowsSelected()}
          indeterminate={table.getIsSomePageRowsSelected()}
          onCheckedChange={(value) => table.toggleAllPageRowsSelected(Boolean(value))}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          aria-label={`选择 ${row.original.id}`}
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(Boolean(value))}
        />
      ),
      enableSorting: false,
      enableHiding: false
    },
    {
      accessorKey: 'id',
      header: 'Task ID',
      cell: ({ row }) => (
        <span className='flex items-center gap-1'>
          <Link href={`/runtime/tasks/${row.original.id}`} className='text-primary hover:underline'>
            <MonoId value={row.original.id} copyable={false} />
          </Link>
        </span>
      ),
      enableSorting: false
    },
    {
      accessorKey: 'title',
      header: 'Title',
      cell: ({ row }) => (
        <Link
          href={`/runtime/tasks/${row.original.id}`}
          className='text-primary-foreground max-w-[240px] truncate font-medium hover:underline'
        >
          {row.original.title}
        </Link>
      ),
      enableSorting: false
    },
    {
      accessorKey: 'hostAppId',
      header: 'Host',
      cell: ({ row }) => <span className='text-sm'>{row.original.hostAppId}</span>,
      filterFn: includesValue,
      enableColumnFilter: true,
      meta: { label: 'Host', variant: 'multiSelect', options: uniqueOptions(input.hosts) }
    },
    {
      accessorKey: 'namespace',
      header: 'Namespace',
      cell: ({ row }) => <span className='font-mono text-xs'>{row.original.namespace}</span>,
      filterFn: includesValue,
      enableColumnFilter: true,
      meta: { label: 'Namespace', variant: 'multiSelect', options: uniqueOptions(input.namespaces) }
    },
    {
      accessorKey: 'agentName',
      header: 'Agent',
      cell: ({ row }) => <span className='text-sm'>{row.original.agentName}</span>,
      filterFn: includesValue,
      enableColumnFilter: true,
      meta: { label: 'Agent', variant: 'multiSelect', options: uniqueOptions(input.agents) }
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => (
        <StatusBadge tone={taskStatusTone(row.original.status)}>
          {TASK_STATUS_LABELS[row.original.status]}
        </StatusBadge>
      ),
      filterFn: includesValue,
      enableColumnFilter: true,
      meta: {
        label: 'Status',
        variant: 'multiSelect',
        options: ALL_STATUSES.map((status) => ({
          value: status,
          label: TASK_STATUS_LABELS[status]
        }))
      }
    },
    {
      accessorKey: 'currentSegment',
      header: 'Current Segment',
      cell: ({ row }) => <span className='font-mono text-xs'>{row.original.currentSegment}</span>,
      enableSorting: false
    },
    {
      accessorKey: 'orchestrationRunRef',
      header: 'Orchestration',
      cell: ({ row }) =>
        row.original.orchestrationRunRef ? (
          <Link
            href={`/runtime/orchestrations/${row.original.orchestrationRunRef}`}
            className='text-primary font-mono text-xs hover:underline'
          >
            {row.original.orchestrationRunRef}
          </Link>
        ) : (
          <span className='text-muted-foreground text-xs'>—</span>
        ),
      enableSorting: false
    },
    {
      accessorKey: 'subagentCount',
      header: 'Subagents',
      cell: ({ row }) => <span className='tabular-nums'>{row.original.subagentCount}</span>,
      enableSorting: false
    },
    {
      id: 'hasSubagent',
      accessorFn: (row) => (row.subagentCount > 0 ? 'true' : 'false'),
      header: 'Has Subagent',
      cell: ({ row }) => (
        <span className='text-sm'>{row.original.subagentCount > 0 ? '是' : '否'}</span>
      ),
      filterFn: includesValue,
      enableColumnFilter: true,
      enableSorting: false,
      meta: {
        label: 'Has Subagent',
        variant: 'multiSelect',
        options: [
          { value: 'true', label: '有子代理' },
          { value: 'false', label: '无子代理' }
        ]
      }
    },
    {
      id: 'waitReason',
      accessorFn: (row) => row.waitReason ?? WAIT_REASON_NONE,
      header: 'Current Wait Reason',
      cell: ({ row }) => (
        <span className='text-muted-foreground max-w-[220px] truncate text-xs'>
          {row.original.waitReason ?? '—'}
        </span>
      ),
      filterFn: includesValue,
      enableColumnFilter: true,
      enableSorting: false,
      meta: {
        label: 'Wait Reason',
        variant: 'multiSelect',
        options: uniqueOptions([...input.waitReasons, WAIT_REASON_NONE], (value) =>
          value === WAIT_REASON_NONE ? '无等待原因' : value
        )
      }
    },
    {
      accessorKey: 'hasClient',
      header: 'Has Client',
      cell: ({ row }) => (
        <span className='text-sm'>{row.original.hasClient ? '有' : '无'}</span>
      ),
      filterFn: includesValue,
      enableColumnFilter: true,
      meta: {
        label: 'Has Client',
        variant: 'multiSelect',
        options: [
          { value: 'true', label: '有前端' },
          { value: 'false', label: '无前端' }
        ]
      }
    },
    {
      accessorKey: 'hasUncertainEffect',
      header: 'Has Uncertain Effect',
      cell: ({ row }) => (
        <span className={row.original.hasUncertainEffect ? 'text-orange-600 dark:text-orange-400 text-sm' : 'text-sm'}>
          {row.original.hasUncertainEffect ? '有' : '无'}
        </span>
      ),
      filterFn: includesValue,
      enableColumnFilter: true,
      meta: {
        label: 'Has Uncertain Effect',
        variant: 'multiSelect',
        options: [
          { value: 'true', label: '有不确定' },
          { value: 'false', label: '无不确定' }
        ]
      }
    },
    {
      accessorKey: 'modelTokens',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Model Tokens' />,
      cell: ({ row }) => <span className='tabular-nums'>{formatNumber(row.original.modelTokens)}</span>
    },
    {
      accessorKey: 'costUsd',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Cost' />,
      cell: ({ row }) => <span className='tabular-nums'>{formatUsd(row.original.costUsd)}</span>
    },
    {
      accessorKey: 'createdAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Created At' />,
      cell: ({ row }) => <span className='text-sm whitespace-nowrap'>{formatDateTime(row.original.createdAt)}</span>
    },
    {
      accessorKey: 'updatedAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Updated At' />,
      cell: ({ row }) => <span className='text-sm whitespace-nowrap'>{relativeTime(row.original.updatedAt)}</span>
    }
  ];
}
