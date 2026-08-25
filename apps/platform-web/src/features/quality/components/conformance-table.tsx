'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import {
  type ColumnDef,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable
} from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { DataTable } from '@/components/ui/table/data-table';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, formatDuration } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { ConformanceRun } from '@/lib/platform/types';

const SURFACE_LABELS: Record<ConformanceRun['surface'], string> = {
  backend: 'Backend',
  frontend: 'Frontend'
};

const RUN_STATUS_LABELS: Record<ConformanceRun['status'], string> = {
  running: '运行中',
  passed: '通过',
  failed: '失败'
};

/**
 * Conformance Run 列表（PRD 16.1）：TanStack 表格 + Surface 筛选 + 手动触发运行。
 */
export function ConformanceTable({
  runs,
  hostOptions
}: {
  runs: ConformanceRun[];
  hostOptions: string[];
}) {
  const [surfaceFilter, setSurfaceFilter] = useState('all');
  const [hostFilter, setHostFilter] = useState('all');
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [dialogHost, setDialogHost] = useState(hostOptions[0] ?? '');
  const [dialogSurface, setDialogSurface] = useState<ConformanceRun['surface']>('backend');

  const columns = useMemo<ColumnDef<ConformanceRun>[]>(
    () => [
      {
        accessorKey: 'id',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Run ID' />,
        cell: ({ row }) => (
          <Link
            href={`/quality/conformance/${row.original.id}`}
            className='text-primary hover:underline font-mono text-xs'
          >
            {row.original.id}
          </Link>
        )
      },
      { accessorKey: 'hostAppId', header: ({ column }) => <DataTableColumnHeader column={column} title='Host' /> },
      {
        accessorKey: 'environment',
        header: 'Environment'
      },
      {
        accessorKey: 'surface',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Surface' />,
        cell: ({ row }) => (
          <StatusBadge
            tone={row.original.surface === 'backend' ? 'running' : 'waiting'}
            withDot={false}
          >
            {SURFACE_LABELS[row.original.surface]}
          </StatusBadge>
        ),
        filterFn: (row, columnId, value: string) =>
          value === 'all' || row.getValue(columnId) === value
      },
      {
        accessorKey: 'profileRevision',
        header: 'Profile Revision',
        cell: ({ row }) => <span className='font-mono text-xs'>rev {row.original.profileRevision}</span>
      },
      {
        accessorKey: 'triggeredBy',
        header: 'Triggered By',
        cell: ({ row }) => <span className='font-mono text-xs'>{row.original.triggeredBy}</span>
      },
      {
        accessorKey: 'startedAt',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Started At' />,
        cell: ({ row }) => (
          <span className='text-muted-foreground text-xs'>
            {formatDateTime(row.original.startedAt)}
          </span>
        )
      },
      {
        accessorKey: 'durationMs',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Duration' />,
        cell: ({ row }) => <span className='tabular-nums'>{formatDuration(row.original.durationMs)}</span>
      },
      {
        accessorKey: 'passed',
        header: 'Passed',
        cell: ({ row }) => (
          <span className='text-emerald-600 dark:text-emerald-400 tabular-nums'>
            {row.original.passed}
          </span>
        )
      },
      {
        accessorKey: 'failed',
        header: 'Failed',
        cell: ({ row }) => (
          <span
            className={
              row.original.failed > 0
                ? 'text-red-600 dark:text-red-400 tabular-nums'
                : 'text-muted-foreground tabular-nums'
            }
          >
            {row.original.failed}
          </span>
        )
      },
      {
        accessorKey: 'skipped',
        header: 'Skipped',
        cell: ({ row }) => <span className='text-muted-foreground tabular-nums'>{row.original.skipped}</span>
      },
      {
        accessorKey: 'status',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Status' />,
        cell: ({ row }) => (
          <StatusBadge tone={lifecycleTone(row.original.status)}>
            {RUN_STATUS_LABELS[row.original.status]}
          </StatusBadge>
        )
      }
    ],
    []
  );

  const data = useMemo(
    () =>
      runs.filter(
        (run) =>
          (surfaceFilter === 'all' || run.surface === surfaceFilter) &&
          (hostFilter === 'all' || run.hostAppId === hostFilter)
      ),
    [runs, surfaceFilter, hostFilter]
  );

  // oxlint-disable-next-line react/incompatible-library -- TanStack Table's useReactTable is incompatible with React Compiler memoization by design; the compiler already skips optimizing this component
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 10 } }
  });

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <Select
          value={surfaceFilter}
          onValueChange={(value) => {
            if (!value) return;
            setSurfaceFilter(value);
            table.getColumn('surface')?.setFilterValue(value);
          }}
        >
          <SelectTrigger className='w-36' aria-label='按 Surface 筛选'>
            <SelectValue placeholder='全部 Surface' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部 Surface</SelectItem>
              <SelectItem value='backend'>Backend</SelectItem>
              <SelectItem value='frontend'>Frontend</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={hostFilter}
          onValueChange={(value) => value && setHostFilter(value)}
        >
          <SelectTrigger className='w-44' aria-label='按 Host 筛选'>
            <SelectValue placeholder='全部 Host' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value='all'>全部 Host</SelectItem>
              {hostOptions.map((host) => (
                <SelectItem key={host} value={host}>
                  {host}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button size='sm' className='ml-auto' onClick={() => setRunDialogOpen(true)}>
          运行 Conformance
        </Button>
      </div>

      <DataTable table={table} />

      <Dialog open={runDialogOpen} onOpenChange={setRunDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>运行 Conformance</DialogTitle>
            <DialogDescription>
              对所选 Host 的指定 Surface 执行标准验收检查，结果计入 Release Gate。
            </DialogDescription>
          </DialogHeader>
          <div className='space-y-3'>
            <div className='space-y-1.5'>
              <span className='text-sm font-medium'>Host</span>
              <Select value={dialogHost} onValueChange={(value) => value && setDialogHost(value)}>
                <SelectTrigger className='w-full' aria-label='选择 Host'>
                  <SelectValue placeholder='选择 Host' />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {hostOptions.map((host) => (
                      <SelectItem key={host} value={host}>
                        {host}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <div className='space-y-1.5'>
              <span className='text-sm font-medium'>Surface</span>
              <Select
                value={dialogSurface}
                onValueChange={(value) =>
                  value && setDialogSurface(value as ConformanceRun['surface'])
                }
              >
                <SelectTrigger className='w-full' aria-label='选择 Surface'>
                  <SelectValue placeholder='选择 Surface' />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value='backend'>Backend</SelectItem>
                    <SelectItem value='frontend'>Frontend</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant='outline' size='sm' onClick={() => setRunDialogOpen(false)}>
              取消
            </Button>
            <Button
              size='sm'
              disabled={!dialogHost}
              onClick={() => {
                setRunDialogOpen(false);
                toast.success('Conformance Run 已创建', {
                  description: `host=${dialogHost} surface=${dialogSurface}（演示）`
                });
              }}
            >
              开始运行
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
