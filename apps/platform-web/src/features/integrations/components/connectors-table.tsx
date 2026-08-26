'use client';

import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';

import { Button } from '@/components/ui/button';
import { DataTableColumnHeader } from '@/components/ui/table/data-table-column-header';
import { DataTable } from '@/components/ui/table/data-table';
import { DataTableToolbar } from '@/components/ui/table/data-table-toolbar';
import { Icons } from '@/components/icons';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { relativeTime } from '@/lib/platform/format';
import type { Connector } from '@/lib/platform/types';
import {
  CONNECTOR_HEALTH_LABELS,
  REVISION_STATUS_LABELS,
  labelOptions
} from '../lib/labels';
import { useMockDataTable } from '../lib/use-mock-data-table';

const columns: ColumnDef<Connector, unknown>[] = [
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
    id: 'id',
    accessorKey: 'id',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Connector ID' />,
    cell: ({ row }) => (
      <Link
        href={`/integrations/connectors/${row.original.id}`}
        className='text-primary font-mono text-xs font-medium hover:underline'
      >
        {row.original.id}
      </Link>
    )
  },
  {
    id: 'baseUri',
    accessorKey: 'baseUri',
    enableSorting: false,
    header: 'Base URI',
    cell: ({ row }) => <span className='font-mono text-xs'>{row.original.baseUri}</span>
  },
  {
    id: 'protocolVersions',
    accessorKey: 'protocolVersions',
    enableSorting: false,
    header: 'Protocol',
    cell: ({ row }) => (
      <span className='text-muted-foreground font-mono text-xs'>
        {row.original.protocolVersions.join('、')}
      </span>
    )
  },
  {
    id: 'credentialRef',
    accessorKey: 'credentialRef',
    enableSorting: false,
    header: 'Credential Ref',
    cell: ({ row }) => (
      <MonoId value={row.original.credentialRef} head={12} tail={0} copyable={false} />
    )
  },
  {
    id: 'latestRevision',
    accessorKey: 'latestRevision',
    header: 'Latest Rev',
    cell: ({ row }) => <span className='font-mono text-xs'>rev {row.original.latestRevision}</span>
  },
  {
    id: 'boundRevision',
    accessorKey: 'boundRevision',
    header: 'Bound Rev',
    cell: ({ row }) => <span className='font-mono text-xs'>rev {row.original.boundRevision}</span>
  },
  {
    id: 'health',
    accessorKey: 'health',
    enableSorting: false,
    header: ({ column }) => <DataTableColumnHeader column={column} title='Health' />,
    cell: ({ row }) => (
      <StatusBadge tone={lifecycleTone(row.original.health)}>
        {CONNECTOR_HEALTH_LABELS[row.original.health]}
      </StatusBadge>
    ),
    enableColumnFilter: true,
    meta: { label: 'Health', variant: 'multiSelect', options: labelOptions(CONNECTOR_HEALTH_LABELS) }
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
    id: 'updatedAt',
    accessorKey: 'updatedAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Updated At' />,
    cell: ({ row }) => (
      <span className='text-muted-foreground text-xs'>{relativeTime(row.original.updatedAt)}</span>
    )
  },
  {
    id: 'actions',
    enableSorting: false,
    header: () => <span className='sr-only'>操作</span>,
    cell: ({ row }) => (
      <Button
        variant='ghost'
        size='icon-sm'
        render={
          <Link
            href={`/integrations/connectors/${row.original.id}`}
            aria-label={`查看 ${row.original.id} 详情`}
          />
        }
      >
        <Icons.chevronRight className='size-4' />
      </Button>
    )
  }
];

const SPEC = {
  textFilters: {
    hostAppId: (row: Connector) => row.hostAppId
  } satisfies Record<string, (row: Connector) => string>,
  selectFilters: {
    health: (row: Connector) => row.health,
    status: (row: Connector) => row.status
  } satisfies Record<string, (row: Connector) => string>,
  sortAccessors: {
    hostAppId: (row: Connector) => row.hostAppId,
    id: (row: Connector) => row.id,
    latestRevision: (row: Connector) => row.latestRevision,
    boundRevision: (row: Connector) => row.boundRevision,
    updatedAt: (row: Connector) => row.updatedAt
  } satisfies Record<string, (row: Connector) => string | number>
};

/** Connector 列表（PRD 11.1）。 */
export function ConnectorsTable({ connectors }: { connectors: Connector[] }) {
  const { table, total } = useMockDataTable({ rows: connectors, columns, spec: SPEC });

  return (
    <div className='flex flex-1 flex-col gap-4'>
      <p className='text-muted-foreground px-1 text-sm'>共 {total} 个 Connector</p>
      <DataTable table={table}>
        <DataTableToolbar table={table} />
      </DataTable>
    </div>
  );
}
