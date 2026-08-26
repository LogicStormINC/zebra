'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import type { ColumnDef } from '@tanstack/react-table';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { DataTable } from '@/components/ui/table/data-table';
import { DataTableToolbar } from '@/components/ui/table/data-table-toolbar';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Icons } from '@/components/icons';
import { DataList } from '@/components/platform/data-list';
import { DigestTag } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { InboundTrust } from '@/lib/platform/types';
import {
  NAMESPACE_STRATEGY_LABELS,
  REVISION_STATUS_LABELS,
  TRUST_HEALTH_LABELS,
  labelOptions
} from '../lib/labels';
import { useMockDataTable } from '../lib/use-mock-data-table';

function TrustDetailDialog({
  trust,
  open,
  onOpenChange
}: {
  trust: InboundTrust | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const runTest = (name: string) =>
    toast.success(`${name} 已执行（演示）`, { description: '结果不会写回平台数据' });

  if (!trust) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-2xl'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            <Icons.trust className='size-4' />
            入站信任 · {trust.hostAppId}
          </DialogTitle>
          <DialogDescription>
            Trust rev {trust.revision} · {REVISION_STATUS_LABELS[trust.status]}
          </DialogDescription>
        </DialogHeader>

        <Alert>
          <Icons.lock />
          <AlertTitle>禁止展示完整 Token</AlertTitle>
          <AlertDescription>
            平台只保存验证结论与 Claim 摘要；完整 Token 不会出现在控制台、日志或审计记录（PRD 13.4）。
          </AlertDescription>
        </Alert>

        <DataList
          columns={2}
          items={[
            { label: 'Host App ID', value: trust.hostAppId },
            { label: 'Issuer', value: <span className='font-mono text-xs'>{trust.issuer}</span> },
            { label: 'Audience', value: <span className='font-mono text-xs'>{trust.audience}</span> },
            { label: 'JWKS URI', value: <span className='font-mono text-xs'>{trust.jwksUri}</span> },
            { label: 'Allowed Origins', value: trust.allowedOrigins.join('、') },
            { label: 'Algorithms', value: trust.algorithms.join('、') },
            { label: 'Policy Version', value: trust.policyVersion },
            {
              label: 'Namespace Strategy',
              value: NAMESPACE_STRATEGY_LABELS[trust.namespaceStrategy]
            },
            { label: 'Clock Skew', value: `${trust.clockSkewSeconds}s` },
            { label: 'Health', value: TRUST_HEALTH_LABELS[trust.health] },
            { label: 'Last Verified', value: formatDateTime(trust.lastVerifiedAt) },
            { label: 'Digest', value: <DigestTag value={trust.digest} /> }
          ]}
        />

        <div className='flex flex-wrap gap-2 border-t pt-3'>
          <Button variant='outline' size='sm' onClick={() => runTest('Test JWKS')}>
            Test JWKS
          </Button>
          <Button variant='outline' size='sm' onClick={() => runTest('Verify Sample Grant')}>
            Verify Sample Grant
          </Button>
          <Button variant='outline' size='sm' onClick={() => runTest('Preview Parsed Claims')}>
            Preview Parsed Claims
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** 入站信任列表（PRD 13）。 */
export function TrustTable({ trusts }: { trusts: InboundTrust[] }) {
  const [selected, setSelected] = useState<InboundTrust | null>(null);

  const columns: ColumnDef<InboundTrust, unknown>[] = [
    {
      id: 'hostAppId',
      accessorKey: 'hostAppId',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Host App ID' />,
      cell: ({ row }) => (
        <span className='font-mono text-xs font-medium'>{row.original.hostAppId}</span>
      ),
      enableColumnFilter: true,
      meta: { label: 'Host App ID', placeholder: '搜索 Host…', variant: 'text' }
    },
    {
      id: 'issuer',
      accessorKey: 'issuer',
      enableSorting: false,
      header: 'Issuer',
      cell: ({ row }) => (
        <span className='font-mono text-xs'>{row.original.issuer}</span>
      )
    },
    {
      id: 'audience',
      accessorKey: 'audience',
      enableSorting: false,
      header: 'Audience',
      cell: ({ row }) => <span className='font-mono text-xs'>{row.original.audience}</span>
    },
    {
      id: 'jwksUri',
      accessorKey: 'jwksUri',
      enableSorting: false,
      header: 'JWKS URI',
      cell: ({ row }) => (
        <span className='text-muted-foreground font-mono text-xs'>{row.original.jwksUri}</span>
      )
    },
    {
      id: 'algorithms',
      accessorKey: 'algorithms',
      enableSorting: false,
      header: 'Algorithms',
      cell: ({ row }) => row.original.algorithms.join('、')
    },
    {
      id: 'namespaceStrategy',
      accessorKey: 'namespaceStrategy',
      enableSorting: false,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Namespace Strategy' />,
      cell: ({ row }) => NAMESPACE_STRATEGY_LABELS[row.original.namespaceStrategy]
    },
    {
      id: 'health',
      accessorKey: 'health',
      enableSorting: false,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Health' />,
      cell: ({ row }) => (
        <StatusBadge tone={lifecycleTone(row.original.health)}>
          {TRUST_HEALTH_LABELS[row.original.health]}
        </StatusBadge>
      ),
      enableColumnFilter: true,
      meta: { label: 'Health', variant: 'multiSelect', options: labelOptions(TRUST_HEALTH_LABELS) }
    },
    {
      id: 'lastVerifiedAt',
      accessorKey: 'lastVerifiedAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title='Last Verified' />,
      cell: ({ row }) => (
        <span className='text-muted-foreground text-xs'>
          {formatDateTime(row.original.lastVerifiedAt)}
        </span>
      )
    },
    {
      id: 'revision',
      accessorKey: 'revision',
      header: 'Revision',
      cell: ({ row }) => <span className='font-mono text-xs'>rev {row.original.revision}</span>
    },
    {
      id: 'digest',
      accessorKey: 'digest',
      enableSorting: false,
      header: 'Digest',
      cell: ({ row }) => <DigestTag value={row.original.digest} />
    },
    {
      id: 'status',
      accessorKey: 'status',
      enableSorting: false,
      header: ({ column }) => <DataTableColumnHeader column={column} title='Status' />,
      cell: ({ row }) => (
        <StatusBadge tone={lifecycleTone(row.original.status)} withDot={false}>
          {REVISION_STATUS_LABELS[row.original.status]}
        </StatusBadge>
      ),
      enableColumnFilter: true,
      meta: {
        label: 'Status',
        variant: 'multiSelect',
        options: labelOptions(REVISION_STATUS_LABELS)
      }
    },
    {
      id: 'actions',
      enableSorting: false,
      header: () => <span className='sr-only'>操作</span>,
      cell: ({ row }) => (
        <Button variant='outline' size='sm' onClick={() => setSelected(row.original)}>
          详情
        </Button>
      )
    }
  ];

  const spec = {
    textFilters: { hostAppId: (row: InboundTrust) => row.hostAppId } satisfies Record<
      string,
      (row: InboundTrust) => string
    >,
    selectFilters: {
      health: (row: InboundTrust) => row.health,
      status: (row: InboundTrust) => row.status
    } satisfies Record<string, (row: InboundTrust) => string>,
    sortAccessors: {
      hostAppId: (row: InboundTrust) => row.hostAppId,
      revision: (row: InboundTrust) => row.revision,
      lastVerifiedAt: (row: InboundTrust) => row.lastVerifiedAt
    } satisfies Record<string, (row: InboundTrust) => string | number>
  };

  const { table, total } = useMockDataTable({ rows: trusts, columns, spec });

  return (
    <div className='flex flex-1 flex-col gap-4'>
      <p className='text-muted-foreground px-1 text-sm'>共 {total} 条入站信任配置</p>
      <DataTable table={table}>
        <DataTableToolbar table={table} />
      </DataTable>
      <TrustDetailDialog
        trust={selected}
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      />
    </div>
  );
}
