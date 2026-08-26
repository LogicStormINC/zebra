'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { DataTableFacetedFilter } from '@/components/ui/table/data-table-faceted-filter';
import { DataTablePagination } from '@/components/ui/table/data-table-pagination';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { DataList } from '@/components/platform/data-list';
import { DigestTag, MonoId } from '@/components/platform/mono-id';
import { JsonBlock } from '@/components/platform/json-block';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { Input } from '@/components/ui/input';
import { formatDateTime } from '@/lib/platform/format';
import type { AuditEntry } from '@/lib/platform/types';
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable
} from '@tanstack/react-table';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { downloadCsv } from '../export-csv';

const ACTOR_TYPE_META: Record<
  AuditEntry['actorType'],
  { label: string; tone: 'running' | 'draft' | 'waiting' }
> = {
  operator: { label: 'Operator', tone: 'running' },
  system: { label: 'System', tone: 'draft' },
  agent: { label: 'Agent', tone: 'waiting' }
};

const RESULT_META: Record<
  AuditEntry['result'],
  { label: string; tone: 'success' | 'failure' | 'uncertain' }
> = {
  succeeded: { label: '成功', tone: 'success' },
  failed: { label: '失败', tone: 'failure' },
  denied: { label: '拒绝', tone: 'uncertain' }
};

const ENVIRONMENT_LABELS: Record<string, string> = {
  production: 'Production',
  staging: 'Staging',
  development: 'Development'
};

export function AuditTable({ entries }: { entries: AuditEntry[] }) {
  const [detail, setDetail] = useState<AuditEntry | null>(null);
  const [sorting, setSorting] = useState<SortingState>([{ id: 'timestamp', desc: true }]);
  // 附加筛选（PRD 23.3 / 35.7.2）：Namespace / Actor 文本包含匹配 + 时间范围
  const [namespaceQuery, setNamespaceQuery] = useState('');
  const [actorQuery, setActorQuery] = useState('');
  const [rangeStart, setRangeStart] = useState('');
  const [rangeEnd, setRangeEnd] = useState('');

  const scopedEntries = useMemo(() => {
    const namespace = namespaceQuery.trim().toLowerCase();
    const actor = actorQuery.trim().toLowerCase();
    return entries.filter((entry) => {
      if (namespace && !(entry.namespace ?? '').toLowerCase().includes(namespace)) return false;
      if (actor && !entry.actor.toLowerCase().includes(actor)) return false;
      const date = entry.timestamp.slice(0, 10);
      if (rangeStart && date < rangeStart) return false;
      if (rangeEnd && date > rangeEnd) return false;
      return true;
    });
  }, [entries, namespaceQuery, actorQuery, rangeStart, rangeEnd]);

  /** 当前附加筛选的描述（用于导出 toast 说明范围）。 */
  const scopeDescription = useMemo(() => {
    const parts: string[] = [];
    if (namespaceQuery.trim()) parts.push(`Namespace 含 "${namespaceQuery.trim()}"`);
    if (actorQuery.trim()) parts.push(`Actor 含 "${actorQuery.trim()}"`);
    if (rangeStart || rangeEnd) {
      parts.push(`时间 ${rangeStart || '最早'} ~ ${rangeEnd || '最新'}`);
    }
    return parts.length > 0 ? parts.join(' · ') : '全部时间与命名空间';
  }, [namespaceQuery, actorQuery, rangeStart, rangeEnd]);

  const columns = useMemo<ColumnDef<AuditEntry>[]>(
    () => [
      {
        accessorKey: 'id',
        header: 'Audit ID',
        cell: ({ row }) => <span className='font-mono text-xs'>{row.original.id}</span>
      },
      {
        accessorKey: 'actor',
        header: 'Actor',
        cell: ({ row }) => <span className='font-mono text-xs'>{row.original.actor}</span>
      },
      {
        accessorKey: 'actorType',
        header: 'Actor Type',
        filterFn: 'arrIncludesSome',
        cell: ({ row }) => (
          <StatusBadge tone={ACTOR_TYPE_META[row.original.actorType].tone} withDot={false}>
            {ACTOR_TYPE_META[row.original.actorType].label}
          </StatusBadge>
        )
      },
      {
        accessorKey: 'action',
        header: 'Action',
        filterFn: 'arrIncludesSome',
        cell: ({ row }) => <span className='font-mono text-xs'>{row.original.action}</span>
      },
      {
        accessorKey: 'resourceType',
        header: 'Resource Type',
        cell: ({ row }) => <span className='text-xs'>{row.original.resourceType}</span>
      },
      {
        accessorKey: 'resourceId',
        header: 'Resource ID',
        cell: ({ row }) => <MonoId value={row.original.resourceId} copyable={false} />
      },
      {
        accessorKey: 'environment',
        header: 'Environment',
        filterFn: 'arrIncludesSome',
        cell: ({ row }) => (
          <Badge variant='secondary' className='text-xs'>
            {ENVIRONMENT_LABELS[row.original.environment] ?? row.original.environment}
          </Badge>
        )
      },
      {
        accessorKey: 'hostAppId',
        header: 'Host',
        filterFn: 'arrIncludesSome',
        cell: ({ row }) => (
          <span className='font-mono text-xs'>{row.original.hostAppId ?? '—'}</span>
        )
      },
      {
        accessorKey: 'result',
        header: 'Result',
        filterFn: 'arrIncludesSome',
        cell: ({ row }) => (
          <StatusBadge tone={RESULT_META[row.original.result].tone}>
            {RESULT_META[row.original.result].label}
          </StatusBadge>
        )
      },
      {
        accessorKey: 'timestamp',
        header: 'Timestamp',
        cell: ({ row }) => (
          <span className='text-muted-foreground text-xs whitespace-nowrap'>
            {formatDateTime(row.original.timestamp)}
          </span>
        )
      }
    ],
    []
  );

  // oxlint-disable-next-line react/incompatible-library -- TanStack Table's useReactTable is incompatible with React Compiler memoization by design; the compiler already skips optimizing this component
  const table = useReactTable({
    data: scopedEntries,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    initialState: { pagination: { pageSize: 10 } }
  });

  const actionOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const entry of entries) {
      counts.set(entry.action, (counts.get(entry.action) ?? 0) + 1);
    }
    return [...counts.entries()]
      .toSorted((a, b) => a[0].localeCompare(b[0]))
      .map(([value, count]) => ({ value, label: value, count }));
  }, [entries]);

  const uniqueOptions = (key: 'actorType' | 'environment' | 'hostAppId' | 'result') => {
    const values = [
      ...new Set(
        entries.map((entry) => entry[key]).filter((value): value is string => Boolean(value))
      )
    ].toSorted();
    return values.map((value) => ({
      value,
      label: key === 'environment' ? (ENVIRONMENT_LABELS[value] ?? value) : value
    }));
  };

  const onExport = () => {
    const rows = table.getFilteredRowModel().rows.map((row) => row.original);
    const csv: (string | number)[][] = [
      [
        'audit_id',
        'actor',
        'actor_type',
        'action',
        'resource_type',
        'resource_id',
        'environment',
        'host',
        'namespace',
        'result',
        'timestamp',
        'correlation_id',
        'before_digest',
        'after_digest',
        'reason'
      ],
      ...rows.map((entry) => [
        entry.id,
        entry.actor,
        entry.actorType,
        entry.action,
        entry.resourceType,
        entry.resourceId,
        entry.environment,
        entry.hostAppId ?? '',
        entry.namespace ?? '',
        entry.result,
        entry.timestamp,
        entry.correlationId,
        entry.beforeDigest ?? '',
        entry.afterDigest ?? '',
        entry.reason ?? ''
      ])
    ];
    const exportDate = rows[0]?.timestamp.slice(0, 10).replaceAll('-', '') ?? 'unknown';
    downloadCsv(`audit-export-${exportDate}.csv`, csv, true);
    toast.success('Audit Log 导出已生成', {
      description: `audit-export-${exportDate}.csv · ${rows.length} 条 · 导出当前筛选后数据（${scopeDescription}）· 范围受当前 Operator 权限限制，文件包含校验摘要`
    });
  };

  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.audit />
        <AlertTitle>审计与导出边界</AlertTitle>
        <AlertDescription>
          Audit Log 追加不可篡改；导出范围受当前 Operator
          权限限制，导出文件附带校验摘要（checksum）用于完整性验证，导出动作本身也会被审计（PRD
          23.3）。
        </AlertDescription>
      </Alert>

      <div className='flex flex-wrap items-center gap-2'>
        <Input
          value={namespaceQuery}
          placeholder='筛选 Namespace…'
          aria-label='筛选 Namespace'
          onChange={(event) => setNamespaceQuery(event.target.value)}
          className='h-8 w-44'
        />
        <Input
          value={actorQuery}
          placeholder='筛选 Actor…'
          aria-label='筛选 Actor'
          onChange={(event) => setActorQuery(event.target.value)}
          className='h-8 w-40'
        />
        <div className='flex items-center gap-1.5'>
          <Input
            type='date'
            value={rangeStart}
            aria-label='开始日期'
            onChange={(event) => setRangeStart(event.target.value)}
            className='h-8 w-[150px]'
          />
          <span className='text-muted-foreground text-xs'>至</span>
          <Input
            type='date'
            value={rangeEnd}
            aria-label='结束日期'
            onChange={(event) => setRangeEnd(event.target.value)}
            className='h-8 w-[150px]'
          />
        </div>
        <DataTableFacetedFilter
          column={table.getColumn('actorType')}
          title='Actor Type'
          options={uniqueOptions('actorType')}
          multiple
        />
        <DataTableFacetedFilter
          column={table.getColumn('action')}
          title='Action'
          options={actionOptions}
          multiple
        />
        <DataTableFacetedFilter
          column={table.getColumn('environment')}
          title='Environment'
          options={uniqueOptions('environment')}
          multiple
        />
        <DataTableFacetedFilter
          column={table.getColumn('hostAppId')}
          title='Host'
          options={uniqueOptions('hostAppId')}
          multiple
        />
        <DataTableFacetedFilter
          column={table.getColumn('result')}
          title='Result'
          options={uniqueOptions('result')}
          multiple
        />
        <div className='ml-auto'>
          <Button size='sm' variant='outline' onClick={onExport}>
            <Icons.externalLink />
            导出
          </Button>
        </div>
      </div>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length > 0 ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className='cursor-pointer'
                  onClick={() => setDetail(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={table.getAllColumns().length}
                  className='text-muted-foreground h-24 text-center'
                >
                  没有匹配的审计记录
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <DataTablePagination table={table} />

      <Dialog open={detail !== null} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className='max-h-[85vh] overflow-y-auto sm:max-w-2xl'>
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className='flex flex-wrap items-center gap-2'>
                  <span className='font-mono text-base'>{detail.id}</span>
                  <StatusBadge tone={RESULT_META[detail.result].tone}>
                    {RESULT_META[detail.result].label}
                  </StatusBadge>
                </DialogTitle>
                <DialogDescription>
                  {detail.action} · {detail.resourceType} · {formatDateTime(detail.timestamp)}
                </DialogDescription>
              </DialogHeader>
              <DataList
                columns={2}
                items={[
                  {
                    label: 'Actor',
                    value: <span className='font-mono text-xs'>{detail.actor}</span>
                  },
                  { label: 'Actor Type', value: ACTOR_TYPE_META[detail.actorType].label },
                  {
                    label: 'Action',
                    value: <span className='font-mono text-xs'>{detail.action}</span>
                  },
                  { label: 'Resource', value: `${detail.resourceType} · ${detail.resourceId}` },
                  {
                    label: 'Environment',
                    value: ENVIRONMENT_LABELS[detail.environment] ?? detail.environment
                  },
                  { label: 'Host', value: detail.hostAppId ?? '—' },
                  { label: 'Namespace', value: detail.namespace ?? '—' },
                  { label: 'Correlation ID', value: <MonoId value={detail.correlationId} /> },
                  {
                    label: 'Before Digest',
                    value: detail.beforeDigest ? <DigestTag value={detail.beforeDigest} /> : '—'
                  },
                  {
                    label: 'After Digest',
                    value: detail.afterDigest ? <DigestTag value={detail.afterDigest} /> : '—'
                  },
                  { label: 'Reason', value: detail.reason ?? '—' },
                  { label: 'Timestamp', value: formatDateTime(detail.timestamp) }
                ]}
              />
              <JsonBlock title={`audit/${detail.id}.json`} value={detail} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
