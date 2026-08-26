'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';

import {
  type ColumnDef,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable
} from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
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
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { ClientEffect, ClientRunBinding, FrontendProfile } from '@/lib/platform/types';
import { CLIENT_EFFECT_STATUS_LABELS } from './labels';
import { ClientEffectDialog } from './client-effect-dialog';

/**
 * Client Effect 列表（PRD 20）：TanStack 表格 + Status 筛选 + 详情 Dialog。
 */
export function ClientEffectsTable({
  effects,
  bindings,
  profiles
}: {
  effects: ClientEffect[];
  bindings: ClientRunBinding[];
  profiles: FrontendProfile[];
}) {
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [selected, setSelected] = useState<ClientEffect | null>(null);

  const statusOptions = useMemo(
    () => ['all', ...Array.from(new Set(effects.map((effect) => effect.status)))],
    [effects]
  );

  const columns = useMemo<ColumnDef<ClientEffect>[]>(
    () => [
      {
        accessorKey: 'id',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Effect ID' />,
        cell: ({ row }) => <MonoId value={row.original.id} copyable={false} />
      },
      {
        accessorKey: 'taskId',
        header: 'Task',
        cell: ({ row }) => (
          <Link
            href={`/runtime/tasks/${row.original.taskId}`}
            className='text-primary hover:underline font-mono text-xs'
          >
            {row.original.taskId}
          </Link>
        )
      },
      {
        accessorKey: 'runId',
        header: 'Run',
        cell: ({ row }) => <span className='font-mono text-xs'>{row.original.runId}</span>
      },
      {
        accessorKey: 'action',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Action' />,
        cell: ({ row }) => <span className='font-mono text-xs'>{row.original.action}</span>
      },
      { accessorKey: 'hostAppId', header: 'Host' },
      { accessorKey: 'frontendAppId', header: 'Frontend App' },
      {
        accessorKey: 'clientSessionId',
        header: 'Client Session',
        cell: ({ row }) => <MonoId value={row.original.clientSessionId} copyable={false} />
      },
      {
        accessorKey: 'status',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Status' />,
        cell: ({ row }) => (
          <StatusBadge tone={lifecycleTone(row.original.status)} withDot={false}>
            {CLIENT_EFFECT_STATUS_LABELS[row.original.status]}
          </StatusBadge>
        ),
        filterFn: (row, columnId, value: string) =>
          value === 'all' || row.getValue(columnId) === value
      },
      {
        accessorKey: 'expectedRevision',
        header: 'Expected Revision',
        cell: ({ row }) => <span className='tabular-nums'>rev {row.original.expectedRevision}</span>
      },
      {
        accessorKey: 'createdAt',
        header: ({ column }) => <DataTableColumnHeader column={column} title='Created' />,
        cell: ({ row }) => (
          <span className='text-muted-foreground text-xs'>
            {formatDateTime(row.original.createdAt)}
          </span>
        )
      },
      {
        accessorKey: 'expiresAt',
        header: 'Expires',
        cell: ({ row }) => (
          <span className='text-muted-foreground text-xs'>
            {formatDateTime(row.original.expiresAt)}
          </span>
        )
      },
      {
        accessorKey: 'receiptDigest',
        header: 'Receipt',
        cell: ({ row }) =>
          row.original.receiptDigest ? (
            <MonoId value={row.original.receiptDigest} head={8} tail={4} copyable={false} />
          ) : (
            <span className='text-muted-foreground'>—</span>
          )
      },
      {
        id: 'detail',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <Button size='xs' variant='outline' onClick={() => setSelected(row.original)}>
            详情
          </Button>
        )
      }
    ],
    []
  );

  const data = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return effects.filter((effect) => {
      if (statusFilter !== 'all' && effect.status !== statusFilter) return false;
      if (!kw) return true;
      return (
        effect.id.toLowerCase().includes(kw) ||
        effect.taskId.toLowerCase().includes(kw) ||
        effect.action.toLowerCase().includes(kw) ||
        effect.clientSessionId.toLowerCase().includes(kw)
      );
    });
  }, [effects, keyword, statusFilter]);

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

  const binding = selected
    ? bindings.find(
        (item) =>
          item.clientSessionId === selected.clientSessionId && item.taskId === selected.taskId
      )
    : undefined;
  const profile = selected
    ? profiles.find(
        (item) =>
          item.hostAppId === selected.hostAppId && item.frontendAppId === selected.frontendAppId
      )
    : undefined;

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <Input
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder='搜索 Effect / Task / Action / Client Session'
          className='h-8 w-72'
          aria-label='搜索 Client Effect'
        />
        <Select
          value={statusFilter}
          onValueChange={(value) => {
            if (!value) return;
            setStatusFilter(value);
            table.getColumn('status')?.setFilterValue(value);
          }}
        >
          <SelectTrigger className='w-44' aria-label='按状态筛选'>
            <SelectValue placeholder='全部状态' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {statusOptions.map((option) => (
                <SelectItem key={option} value={option}>
                  {option === 'all'
                    ? '全部状态'
                    : CLIENT_EFFECT_STATUS_LABELS[option as ClientEffect['status']]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      <DataTable table={table} />

      <ClientEffectDialog
        effect={selected}
        open={selected !== null}
        onOpenChange={(open) => !open && setSelected(null)}
        bindingSnapshotDigest={binding?.snapshotDigest}
        profileDigest={profile?.digest}
      />
    </div>
  );
}
